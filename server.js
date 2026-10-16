require('dotenv').config();
const express = require('express');
const axios = require('axios');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');
const { loadAccounts, isAuthorized, createSession, readSession } = require('./prospeccao-auth');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = process.env.PORT || 3000;

// Configurações do Chatwoot
let CHATWOOT_URL = process.env.CHATWOOT_URL || 'https://chatwoot.segredosdodrop.com';
if (CHATWOOT_URL.endsWith('/')) CHATWOOT_URL = CHATWOOT_URL.slice(0, -1);

const PLATFORM_TOKEN = process.env.PLATFORM_TOKEN;
const CHATWOOT_USER_ID = process.env.CHATWOOT_USER_ID || 1;

// Configurações do Supabase
const SUPABASE_URL = process.env.SUPABASE_URL || 'https://quantic-supabase.k5jwra.easypanel.host';
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY || process.env.SUPABASE_KEY;

// Configurações do Meta Marketing API (Facebook Ads)
const META_ACCESS_TOKEN = process.env.META_ACCESS_TOKEN;
const META_AD_ACCOUNT_ID = process.env.META_AD_ACCOUNT_ID;
const META_API_VERSION = process.env.META_API_VERSION || 'v21.0';

// 1. Endpoints do Dashboard (Devem vir PRIMEIRO)
app.get('/api/config', (req, res) => {
    res.json({ supabaseUrl: SUPABASE_URL, supabaseAnonKey: SUPABASE_ANON_KEY });
});

// Redireciona a raiz pra Custos (página Desempenho desativada)
app.get('/', (req, res) => res.redirect('/custos.html'));
app.get('/index.html', (req, res) => res.redirect('/custos.html'));

// ========== META ADS (Marketing API) ==========
// Proxy server-side: o token NUNCA vai pro front
function metaError(res, error) {
    console.error('❌ Meta API:', error?.response?.data || error.message);
    res.status(error?.response?.status || 500).json({
        error: error?.response?.data?.error?.message || error.message,
        code: error?.response?.data?.error?.code,
        type: error?.response?.data?.error?.type
    });
}

// Insights agregados (totais + breakdown opcional por dia)
// Query: ?since=YYYY-MM-DD&until=YYYY-MM-DD&breakdown=daily
app.use('/api/meta', (req, res, next) => autenticaProspeccao(req, res, () => {
    if (req.headers['x-prospeccao-user'] !== 'lucas') return res.status(403).json({error:'Acesso exclusivo do Lucas.'});
    next();
}));
app.get('/api/meta/insights', async (req, res) => {
    if (!META_ACCESS_TOKEN || !META_AD_ACCOUNT_ID) {
        return res.status(500).json({ error: 'META_ACCESS_TOKEN ou META_AD_ACCOUNT_ID não configurados' });
    }
    try {
        const since = req.query.since;
        const until = req.query.until;
        if (!since || !until) return res.status(400).json({ error: 'since e until são obrigatórios (YYYY-MM-DD)' });
        const breakdown = req.query.breakdown === 'daily' ? '&time_increment=1' : '';
        const fields = 'spend,impressions,clicks,ctr,cpc,cpm,reach,actions,action_values,date_start,date_stop';
        const url = `https://graph.facebook.com/${META_API_VERSION}/${META_AD_ACCOUNT_ID}/insights` +
            `?fields=${fields}` +
            `&time_range=${encodeURIComponent(JSON.stringify({ since, until }))}` +
            breakdown +
            `&access_token=${META_ACCESS_TOKEN}`;
        const r = await axios.get(url, { timeout: 15000 });
        res.json(r.data);
    } catch (e) { metaError(res, e); }
});

// Por campanha
// Query: ?since=YYYY-MM-DD&until=YYYY-MM-DD
app.get('/api/meta/campaigns', async (req, res) => {
    if (!META_ACCESS_TOKEN || !META_AD_ACCOUNT_ID) {
        return res.status(500).json({ error: 'META_ACCESS_TOKEN ou META_AD_ACCOUNT_ID não configurados' });
    }
    try {
        const since = req.query.since;
        const until = req.query.until;
        if (!since || !until) return res.status(400).json({ error: 'since e until são obrigatórios' });
        const fields = 'campaign_id,campaign_name,spend,impressions,clicks,ctr,cpc,cpm,reach,actions,action_values,objective';
        const url = `https://graph.facebook.com/${META_API_VERSION}/${META_AD_ACCOUNT_ID}/insights` +
            `?level=campaign&fields=${fields}` +
            `&time_range=${encodeURIComponent(JSON.stringify({ since, until }))}` +
            `&limit=200&access_token=${META_ACCESS_TOKEN}`;
        const r = await axios.get(url, { timeout: 15000 });
        res.json(r.data);
    } catch (e) { metaError(res, e); }
});

// Metadados da conta (nome, currency, timezone) — pra mostrar no header
app.get('/api/meta/account', async (req, res) => {
    if (!META_ACCESS_TOKEN || !META_AD_ACCOUNT_ID) {
        return res.status(500).json({ error: 'META_ACCESS_TOKEN ou META_AD_ACCOUNT_ID não configurados' });
    }
    try {
        const url = `https://graph.facebook.com/${META_API_VERSION}/${META_AD_ACCOUNT_ID}` +
            `?fields=name,currency,timezone_name,account_status&access_token=${META_ACCESS_TOKEN}`;
        const r = await axios.get(url, { timeout: 10000 });
        res.json(r.data);
    } catch (e) { metaError(res, e); }
});

app.get('/api/chatwoot/sso', async (req, res) => {
    try {
        if (!PLATFORM_TOKEN) throw new Error('PLATFORM_TOKEN missing');
        const response = await axios.get(
            `${CHATWOOT_URL}/platform/api/v1/users/${CHATWOOT_USER_ID}/login`,
            { headers: { api_access_token: PLATFORM_TOKEN }, timeout: 10000 }
        );
        if (response.data && response.data.url) {
            // Retorna apenas o caminho relativo para o iframe usar o proxy do root
            const ssoPath = response.data.url.replace(CHATWOOT_URL, '');
            return res.json({ success: true, ssoUrl: ssoPath });
        }
        throw new Error('Invalid response from Chatwoot');
    } catch (error) {
        console.error('❌ Erro SSO:', error.message);
        res.status(500).json({ success: false, error: 'Falha ao acessar Chatwoot', details: error.message });
    }
});

// 2a-bis. Photo Maker (Next.js) — servido sob /fotos/*
// Roda em processo separado na PORT_PHOTO_MAKER (padrão 3001) dentro do mesmo container.
// O Next foi buildado com NEXT_BASE_PATH=/fotos, então atende exatamente nesse prefixo.
// Filtramos por função pra preservar o /fotos na URL (Express strip mount path).
const PHOTO_MAKER_PORT = process.env.PHOTO_MAKER_PORT || 3001;
const photoMakerProxy = createProxyMiddleware({
    target: `http://localhost:${PHOTO_MAKER_PORT}`,
    changeOrigin: true,
    ws: true,
});
app.use((req, res, next) => {
    if (req.url === '/fotos' || req.url.startsWith('/fotos/')) {
        return photoMakerProxy(req, res, next);
    }
    next();
});

// Desempenho diário por anúncio armazenado no Supabase.
// Retorna somente métricas comerciais necessárias ao painel; a chave de serviço
// permanece no servidor. O intervalo é limitado para evitar consultas amplas.
app.get('/api/meta/creatives', async (req, res) => {
    const serviceKey = process.env.META_DATA_SERVICE_KEY || (fs.existsSync('/data/prospeccao/meta-data-key') ? fs.readFileSync('/data/prospeccao/meta-data-key', 'utf8').trim() : process.env.SUPABASE_KEY);
    const since = String(req.query.since || '');
    const until = String(req.query.until || '');
    const validDay = /^\d{4}-\d{2}-\d{2}$/;
    if (!serviceKey) return res.status(500).json({ error: 'Fonte de investimento não configurada' });
    if (!validDay.test(since) || !validDay.test(until)) {
        return res.status(400).json({ error: 'since e until são obrigatórios (YYYY-MM-DD)' });
    }
    const fromTime = Date.parse(`${since}T12:00:00Z`);
    const toTime = Date.parse(`${until}T12:00:00Z`);
    const rangeDays = Math.round((toTime - fromTime) / 86400000) + 1;
    if (!Number.isFinite(rangeDays) || rangeDays < 1 || rangeDays > 186) {
        return res.status(400).json({ error: 'O período consultado deve ter entre 1 e 186 dias, incluindo a comparação anterior' });
    }
    try {
        const endpoint = `${SUPABASE_URL}/rest/v1/meta_ads_criativos`;
        const r = await axios.get(endpoint, {
            params: {
                select: 'dia,account_id,campaign_name,adset_name,ad_id,ad_name,spend,impressions,clicks,link_clicks,landing_page_views,leads',
                and: `(dia.gte.${since},dia.lte.${until})`,
                order: 'dia.asc',
                limit: '10000'
            },
            headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` },
            timeout: 15000
        });
        res.json({ data: r.data });
    } catch (e) { metaError(res, e); }
});

// 2a-ter. Painel de prospecção — processo Python interno protegido por acesso próprio.
// A credencial anterior continua válida; usuários adicionais têm senha própria.
// Configure somente hashes no ambiente do serviço, nunca no Git.
const LUCAS_AUTH_FILE = '/data/prospeccao/lucas-auth.json';
const PROSPECCAO_ENV = { ...process.env };
const PROSPECCAO_REVOKED_BEFORE = {};
if (fs.existsSync(LUCAS_AUTH_FILE)) {
    const credential = JSON.parse(fs.readFileSync(LUCAS_AUTH_FILE, 'utf8'));
    if (PROSPECCAO_ENV.PROSPECCAO_USER !== 'lucas' ||
        !/^[a-f0-9]{64}$/.test(credential.hash) || !Number.isFinite(credential.invalidBefore)) {
        throw new Error('Credencial persistente do Lucas inválida.');
    }
    PROSPECCAO_ENV.PROSPECCAO_PASSWORD_HASH = credential.hash;
    PROSPECCAO_REVOKED_BEFORE[PROSPECCAO_ENV.PROSPECCAO_USER] = credential.invalidBefore;
}
const PROSPECCAO_ACCOUNTS = loadAccounts(PROSPECCAO_ENV);
const PROSPECCAO_SESSION_SECRET = process.env.PROSPECCAO_SESSION_SECRET || crypto.randomBytes(32).toString('hex');
// Atrás do proxy do EasyPanel: sem isso req.ip é o IP do proxy e o limite de
// tentativas de login vira um contador único pra TODO mundo (um trava o outro).
app.set('trust proxy', 1);
const loginAttempts = new Map();
const PROSPECCAO_API = /^\/api\/(recebidas|fila|conversas|comissoes(?:\/marcar)?|tarefas(?:\/(?:salvar|excluir))?|grupos\/vincular|disparo|envio|contagem|metas\/(?:conversas|config|responsaveis)|midia|conversa|crm(?:\/.*)?|ocultar|status|responsavel|lead\/(?:excluir|historico|jornada)|jornada\/catalogos30|enviar|mensagem\/(?:editar|excluir)|audio|combo|combo_status|catalogo(?:\/video)?|gravado|atualizar|prontos|mensagens(?:\/.*)?|encaminhar|sync|sugestao|sugestao_etapa|assistente(?:\/conversas?)?|events)(?:\?|$)/;

function origemProspeccaoValida(req) {
    const origem = req.headers.origin;
    if (req.headers['sec-fetch-site'] === 'cross-site') return false;
    if (!origem) return true;
    try { return new URL(origem).host === req.headers.host; }
    catch (_) { return false; }
}

function usuarioDaSessao(req) {
    const cookie = (req.headers.cookie || '').split(';').map(part => part.trim()).find(part => part.startsWith('prospeccao_session='));
    return readSession(cookie?.slice('prospeccao_session='.length), PROSPECCAO_SESSION_SECRET,
        PROSPECCAO_ACCOUNTS, Date.now(), PROSPECCAO_REVOKED_BEFORE);
}

function autenticaProspeccao(req, res, next) {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method) && !origemProspeccaoValida(req)) return res.sendStatus(403);
    const usuario = usuarioDaSessao(req) || (() => {
        if (!isAuthorized(req.headers.authorization, PROSPECCAO_ACCOUNTS)) return null;
        return Buffer.from(req.headers.authorization.slice(6), 'base64').toString('utf8').split(':')[0];
    })();
    if (usuario) {
        req.headers['x-prospeccao-user'] = usuario;
        res.setHeader('Cache-Control', 'no-store');
        return next();
    }
    res.setHeader('Cache-Control', 'no-store');
    if (req.path === '/prospeccao/' || req.path === '/prospeccao') return res.redirect(303, '/prospeccao/login');
    return res.status(401).json({ error: 'Faça login para acessar o painel.' });
}

app.get('/prospeccao/login', (req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    if (usuarioDaSessao(req)) return res.redirect('/crm/pipeline');
    res.sendFile(path.join(__dirname, 'prospeccao-login.html'));
});

app.post('/prospeccao/session', express.json({ limit: '4kb' }), (req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    if (!origemProspeccaoValida(req)) return res.sendStatus(403);
    const ip = req.ip;
    const now = Date.now();
    const attempts = loginAttempts.get(ip) || { count: 0, until: now + 15 * 60 * 1000 };
    if (attempts.until < now) { attempts.count = 0; attempts.until = now + 15 * 60 * 1000; }
    if (attempts.count >= 10) return res.status(429).json({ error: 'Muitas tentativas. Tente novamente em alguns minutos.' });
    const { usuario, senha } = req.body || {};
    if (typeof usuario !== 'string' || typeof senha !== 'string' || usuario.length > 100 || senha.length > 200 ||
        !isAuthorized(`Basic ${Buffer.from(`${usuario}:${senha}`).toString('base64')}`, PROSPECCAO_ACCOUNTS)) {
        attempts.count++;
        loginAttempts.set(ip, attempts);
        return res.status(401).json({ error: 'Usuário ou senha incorretos.' });
    }
    loginAttempts.delete(ip);
    res.cookie('prospeccao_session', createSession(usuario, PROSPECCAO_SESSION_SECRET), {
        httpOnly: true, sameSite: 'lax', secure: req.secure || req.headers['x-forwarded-proto'] === 'https',
        path: '/', maxAge: 7 * 24 * 60 * 60 * 1000,
    });
    res.json({ ok: true });
});

app.post('/prospeccao/logout', (req, res) => {
    if (!origemProspeccaoValida(req)) return res.sendStatus(403);
    res.clearCookie('prospeccao_session', { path: '/' });
    res.json({ ok: true });
});

const prospeccaoProxy = createProxyMiddleware({
    target: 'http://127.0.0.1:8781',
    // O Python valida Origin contra Host; preserve o domínio público.
    changeOrigin: false,
    proxyTimeout: 0,
    timeout: 0,
});

app.get(/^\/prospeccao$/, autenticaProspeccao, (_req, res) => res.redirect('/prospeccao/'));
const prospeccaoPageProxy = createProxyMiddleware({
    target: 'http://127.0.0.1:8781',
    changeOrigin: true,
    proxyTimeout: 0,
    timeout: 0,
    pathRewrite: { '^/prospeccao': '' },
});
app.use((req, res, next) => {
    if (req.url !== '/prospeccao/' && !req.url.startsWith('/prospeccao/?')) return next();
    return autenticaProspeccao(req, res, () => prospeccaoPageProxy(req, res, next));
});

// A tela usa caminhos absolutos /api/*. Encaminhamos somente os endpoints do
// painel, preservando as APIs já existentes do Quantic Dash.
app.use((req, res, next) => {
    if (!PROSPECCAO_API.test(req.originalUrl)) return next();
    return autenticaProspeccao(req, res, () => prospeccaoProxy(req, res, next));
});

// 2a. CRM (React SPA) — servido sob /crm/*
const CRM_DIST = path.join(__dirname, 'crm-app', 'dist');
app.use('/crm', express.static(CRM_DIST));
// SPA fallback: qualquer rota do React Router dentro do /crm/ retorna o index.html
app.get(/^\/crm(\/.*)?$/, (req, res, next) => {
    const fs = require('fs');
    const indexPath = path.join(CRM_DIST, 'index.html');
    if (!fs.existsSync(indexPath)) return next();
    res.sendFile(indexPath);
});

// 2b. Servir arquivos estáticos do Dashboard (HTML/CSS/JS raiz)
// Se o arquivo existir na pasta local, ele será entregue.
app.use('/pl-atendimento', (_req, res) => res.sendStatus(404));
app.use(express.static(__dirname));

// 3. PROXY CATCH-ALL (O "Coringa")
// Qualquer rota que não seja um arquivo local ou uma rota definida acima será enviada ao Chatwoot.
// Isso resolve AUTOMATICAMENTE todos os erros 404 de ativos (/vite, /assets, /brand-assets, etc).
app.use('/', createProxyMiddleware({
    target: CHATWOOT_URL,
    changeOrigin: true,
    secure: false,
    ws: true, // Suporte a WebSockets para tempo real
    onProxyRes: (proxyRes) => {
        // Remove as travas de segurança de TODAS as respostas do Chatwoot
        delete proxyRes.headers['x-frame-options'];
        delete proxyRes.headers['content-security-policy'];
        proxyRes.headers['X-Frame-Options'] = 'ALLOWALL';
        proxyRes.headers['Access-Control-Allow-Origin'] = '*';
    },
    cookieDomainRewrite: "" // Reescreve os cookies para o domínio do seu dashboard
}));

app.listen(PORT, () => {
    console.log(`🚀 Quantic Dashboard em modo Híbrido ativo na porta ${PORT}`);
});
