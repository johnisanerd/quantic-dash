"""Integração local com o mesmo Supabase do Quantic Dash (sem dependências)."""
import json
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import etapas
import jornada

# Etapas oferecidas no painel: só o funil novo (slugs antigos o banco converte sozinho).
ETAPAS = {slug: etapas.ROTULO_CRM[slug] for _, slug in etapas.FUNIL}


def telefone(value):
    digits = re.sub(r'\D', '', value or '')
    if digits.startswith('00'):
        digits = digits[2:]
    if len(digits) in (10, 11):
        digits = '55' + digits
    # Unifica a versão brasileira com/sem o nono dígito de celular.
    if digits.startswith('55') and len(digits) == 13 and digits[4] == '9':
        digits = digits[:4] + digits[5:]
    return digits


def anuncio(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if unicodedata.category(c) != 'Mn')
    return bool(re.search(r'(?:gostaria de|quero) saber mais sobre o (?:provou catalogo|provador virtual)', text))


class CRM:
    def __init__(self, connect):
        self.connect = connect
        self.lock = threading.RLock()
        self.chat_locks = {}
        self.chat_locks_guard = threading.Lock()
        self.wakeup = threading.Event()
        self.index = None
        self.index_at = 0
        self.sync_status = {'erro': '', 'registrados': 0}
        env = {}
        path = Path(os.environ.get('PL_CRM_ENV_FILE', str(
            Path(__file__).resolve().parent.parent / 'crm-app' / '.env.production')))
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    env[key.strip()] = value.strip().strip('\"\'')
        self.url = os.environ.get('PL_CRM_URL') or env.get('VITE_SUPABASE_URL', '')
        self.key = os.environ.get('PL_CRM_KEY') or env.get('VITE_SUPABASE_ANON_KEY', '')

    def chat_lock(self, chatid):
        with self.chat_locks_guard:
            return self.chat_locks.setdefault(chatid, threading.RLock())

    def notify_messages(self):
        self.wakeup.set()

    def setup(self):
        c = self.connect()
        c.execute('CREATE TABLE IF NOT EXISTS crm_links (chatid TEXT PRIMARY KEY, lead_id TEXT NOT NULL)')
        jornada.init(c)
        c.commit()

    def request(self, table, query=None, method='GET', body=None, prefer=None):
        if not self.url or not self.key:
            raise ValueError('Configure PL_CRM_ENV_FILE ou PL_CRM_URL e PL_CRM_KEY no servidor.')
        url = self.url.rstrip('/') + '/rest/v1/' + table
        if query:
            url += '?' + urllib.parse.urlencode(query)
        headers = {'apikey': self.key, 'Authorization': 'Bearer ' + self.key,
                   'Content-Type': 'application/json'}
        if prefer:
            headers['Prefer'] = prefer
        req = urllib.request.Request(url, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                data = response.read()
                return json.loads(data) if data else None
        except urllib.error.HTTPError as exc:
            raise RuntimeError('Quantic Dash recusou a operação (HTTP %s). Verifique permissões e dados.' % exc.code) from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('Sem conexão com o Quantic Dash. Tente novamente.') from None

    def remote_lead(self, lead_id):
        rows = self.request('leads', {'id': 'eq.' + lead_id,
                            'select': 'id,nome_loja,status,telefone,email,instagram,site,fonte_oportunidade,notas,created_at'})
        if len(rows) != 1:
            raise ValueError('Lead vinculado não está acessível no CRM.')
        row = rows[0]
        custom = self.request('crm_lead_etapas', {'lead_id': 'eq.' + lead_id, 'select': 'status'})
        if custom:
            row['status'] = custom[0]['status']
        return row

    def details(self, chatid):
        lead = self.ensure(chatid)
        notes = self.request('interacoes', {'lead_id': 'eq.' + lead['id'], 'tipo': 'eq.nota',
                             'select': 'id,conteudo,created_at', 'order': 'created_at.desc', 'limit': 20}) if lead else []
        return {'lead': lead, 'etapas': ETAPAS, 'notas': notes}

    def reflect_local(self, chatid, lead, origem='crm', por=None):
        """Os filtros locais acompanham a etapa confirmada, inclusive encerramentos.
        Toda troca de etapa vista aqui vai pro etapa_historico (aba Jornada); origem 'crm' = mudou fora do painel."""
        status = etapas.local_do_slug(lead['status'])
        c = self.connect()
        antes = c.execute('SELECT status FROM leads WHERE chatid=?', (chatid,)).fetchone()
        c.execute('UPDATE leads SET status=? WHERE chatid=?', (status, chatid))
        if antes is not None and (antes[0] or '') != status:
            jornada.registra_etapa(c, chatid, antes[0], status, origem, por)
        c.commit()
        return lead

    def phone_index(self):
        if self.index is not None and time.monotonic() - self.index_at < 60:
            return self.index
        index, offset = {}, 0
        while True:
            rows = self.request('leads', {'select': 'id,telefone,whatsapp', 'order': 'id',
                                          'limit': 1000, 'offset': offset})
            for row in rows:
                for field in ('telefone', 'whatsapp'):
                    number = telefone(str(row.get(field) or ''))
                    if number:
                        index.setdefault(number, set()).add(row['id'])
            if len(rows) < 1000:
                break
            offset += len(rows)
        self.index, self.index_at = index, time.monotonic()
        return index

    def ensure(self, chatid, create=False):
        # Already linked chats do not wait for the global phone-index scan.
        with self.chat_lock(chatid):
            c = self.connect()
            linked = c.execute('SELECT lead_id FROM crm_links WHERE chatid=?', (chatid,)).fetchone()
            if linked:
                return self.reflect_local(chatid, self.remote_lead(linked['lead_id']))
            return self.ensure_unlinked(chatid, create)

    def ensure_unlinked(self, chatid, create=False):
        with self.lock:
            c = self.connect()
            local = c.execute('SELECT * FROM leads WHERE chatid=?', (chatid,)).fetchone()
            if not local:
                raise ValueError('Conversa não encontrada.')
            linked = c.execute('SELECT lead_id FROM crm_links WHERE chatid=?', (chatid,)).fetchone()
            if linked:
                return self.reflect_local(chatid, self.remote_lead(linked['lead_id']))
            number = telefone(local['fone'])
            if not 10 <= len(number) <= 15 or not chatid.endswith('@s.whatsapp.net'):
                raise ValueError('A conversa não possui um telefone individual válido para vincular.')
            matches = self.phone_index().get(number, set())
            if len(matches) > 1:
                raise ValueError('Há mais de um lead com esse telefone no CRM. Resolva a duplicidade no Quantic Dash.')
            if matches:
                lead_id = next(iter(matches))
            elif not create:
                return None
            else:
                messages = c.execute('SELECT texto FROM mensagens WHERE chatid=? AND from_me=0 ORDER BY ts', (chatid,)).fetchall()
                ad = next((r['texto'] for r in messages if anuncio(r['texto'] or '')), None)
                # Chave determinística: retries não duplicam e não redefinem etapa.
                handle = 'whatsapp_' + number
                self.request('leads', {'on_conflict': 'instagram'}, 'POST', {
                    'instagram': handle, 'nome_loja': local['nome'] or local['fone'],
                    'telefone': local['fone'], 'status': etapas.PARA_CRM.get(local['status']) or ('novo' if ad else 'respondeu'),
                    'fonte_oportunidade': 'Meta' if ad else 'WhatsApp',
                    'notas': 'Registrado pelo PL Atendimento. Instagram não informado.' +
                             ('\nMensagem de entrada: ' + ad if ad else ''),
                }, 'resolution=ignore-duplicates,return=minimal')
                rows = self.request('leads', {'instagram': 'eq.' + handle, 'select': 'id'})
                if len(rows) != 1:
                    raise ValueError('Não foi possível confirmar o cadastro no CRM.')
                lead_id = rows[0]['id']
                self.index.setdefault(number, set()).add(lead_id)
            lead = self.remote_lead(lead_id)
            c.execute('INSERT OR REPLACE INTO crm_links VALUES (?,?)', (chatid, lead_id))
            c.commit()
            return self.reflect_local(chatid, lead)

    def change(self, chatid, status, origem='manual', por=None):
        if status not in ETAPAS:
            raise ValueError('Etapa inválida.')
        with self.chat_lock(chatid):
            lead = self.ensure(chatid, create=True)
            lead_id = lead['id']
            custom_bases = {'testou_e_saiu': 'stand_by', 'teste_catalogo_7_dias': 'testando'}
            if status in custom_bases:
                self.request('leads', {'id': 'eq.' + lead_id}, 'PATCH', {'status': custom_bases[status]}, 'return=representation')
                self.request('crm_lead_etapas', {'on_conflict': 'lead_id'}, 'POST',
                             {'lead_id': lead_id, 'status': status}, 'resolution=merge-duplicates')
            else:
                self.request('leads', {'id': 'eq.' + lead_id}, 'PATCH', {'status': status}, 'return=representation')
                self.request('crm_lead_etapas', {'lead_id': 'eq.' + lead_id}, 'DELETE')
            saved = self.remote_lead(lead_id)
            if saved['status'] != status:
                raise ValueError('A alteração não foi confirmada pelo CRM. Atualize e tente novamente.')
            return self.reflect_local(chatid, saved, origem, por)

    def add_note(self, chatid, content):
        text = str(content or '').strip()
        if not text:
            raise ValueError('Digite uma observação antes de salvar.')
        if len(text) > 2000:
            raise ValueError('A observação pode ter no máximo 2.000 caracteres.')
        with self.chat_lock(chatid):
            lead = self.ensure(chatid, create=True)
            now = datetime.now(timezone.utc).isoformat()
            rows = self.request('interacoes', method='POST', body={
                'lead_id': lead['id'], 'tipo': 'nota', 'conteudo': text,
                'created_at': now,
            }, prefer='return=representation')
            self.request('leads', {'id': 'eq.' + lead['id']}, 'PATCH',
                         {'updated_at': now}, 'return=minimal')
            if not rows:
                raise ValueError('O CRM não confirmou a observação. Tente novamente.')
            return rows[0]

    def sync(self):
        """Recupera também entradas antigas reconhecidas; falhas ficam para o próximo ciclo."""
        c = self.connect()
        rows = c.execute('SELECT DISTINCT l.chatid,m.texto FROM leads l JOIN mensagens m ON m.chatid=l.chatid '
                         'LEFT JOIN crm_links k ON k.chatid=l.chatid WHERE k.chatid IS NULL '
                         'AND COALESCE(l.oculto,0)=0 AND m.from_me=0 ORDER BY l.ultimo_ts DESC').fetchall()
        candidates = list(dict.fromkeys(r['chatid'] for r in rows if anuncio(r['texto'] or '')))[:25]
        errors = 0
        for chatid in candidates:
            try:
                self.ensure(chatid, create=True)
                self.sync_status['registrados'] += 1
            except Exception:
                errors += 1
        self.sync_status['erro'] = ('%d cadastro(s) pendente(s) no CRM; nova tentativa automática.' % errors) if errors else ''

    def pull_statuses(self):
        """Traz pro painel as etapas mudadas fora dele (agente de catálogos, rotina do funil, Quantic Dash)."""
        c = self.connect()
        por_lead = {}
        for r in c.execute('SELECT chatid, lead_id FROM crm_links'):
            por_lead.setdefault(r['lead_id'], []).append(r['chatid'])
        ids = list(por_lead)
        for i in range(0, len(ids), 150):
            for row in self.request('leads', {'select': 'id,status', 'id': 'in.(' + ','.join(ids[i:i + 150]) + ')'}):
                novo = etapas.local_do_slug(row['status'])
                for chatid in por_lead.get(row['id'], []):
                    antes = c.execute('SELECT status FROM leads WHERE chatid=?', (chatid,)).fetchone()
                    if antes is not None and (antes[0] or '') != novo:
                        c.execute('UPDATE leads SET status=? WHERE chatid=?', (novo, chatid))
                        jornada.registra_etapa(c, chatid, antes[0], novo, 'crm')
        c.commit()

    def loop(self):
        while True:
            try:
                self.pull_statuses()
            except Exception:
                pass
            try:
                self.sync()
            except Exception:
                self.sync_status['erro'] = 'Sincronização com CRM pendente; nova tentativa automática.'
            self.wakeup.wait(60)
            self.wakeup.clear()
