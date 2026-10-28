"""
Coleta leads via Google Shopping → site direto:
1. Busca produtos no Google Shopping (queries por categoria/idioma)
2. Extrai merchants + URL dos produtos
3. Acessa o site (homepage do dominio do produto), valida e-commerce + extrai WhatsApp
4. Salva leads que tem WhatsApp + sao e-commerce real

Sem dependencia de Instagram Search — mais economico em creditos Apify.
"""
import argparse
import json
import os
from urllib.parse import urlparse

import requests
from apify_client import ApifyClient

from config import APIFY_TOKEN, DATA_DIR, LEADS_BRUTOS_PATH
from verificador import extrair_whatsapp, eh_ecommerce, eh_brasileiro

SHOPPING_QUERIES = {
    ("oculos", "pt"): ["oculos de sol", "oculos de grau", "oculos polarizado", "armacao de oculos"],
    ("oculos", "en"): ["sunglasses", "eyewear", "eyeglasses"],
    ("oculos", "es"): ["gafas de sol", "lentes de sol", "anteojos"],
    ("roupa", "pt"): [
        "vestido feminino", "camiseta estampada", "calca jeans feminina",
        "blusa feminina", "moletom unissex", "biquini", "maio",
        "short masculino", "camisa social", "jaqueta masculina",
        "lingerie feminina", "pijama", "casaco feminino",
        "body feminino", "cropped feminino", "saia midi",
        "vestido longo", "vestido festa", "vestido curto",
        "camiseta basica", "blazer feminino", "macacao feminino",
        "vestido boho", "kimono", "tactel moletom",
    ],
    ("roupa", "en"): ["women dress", "men t-shirt", "hoodie", "swimwear"],
    ("roupa", "es"): ["vestido mujer", "camiseta hombre", "sudadera"],
}

# Marketplaces a bloquear (queremos lojas autorais)
BLOCKED_MERCHANTS = [
    "amazon", "ebay", "mercado livre", "mercadolivre", "magalu", "magazine luiza",
    "americanas", "submarino", "shoppe", "shopee", "aliexpress", "wish",
    "shein", "dafiti", "walmart", "target", "costco", "best buy",
    "ray-ban", "oakley", "persol", "zara", "c&a", "renner", "riachuelo",
    "marisa", "hering", "lojas torra", "nike", "adidas", "puma", "decathlon",
    "kanui", "netshoes", "centauro", "lupo", "youcom", "track e field",
    "google", "bing",
]

BLOCKED_DOMAINS = [
    "amazon.", "mercadolivre.", "shopee.", "americanas.", "submarino.",
    "magalu.", "magazineluiza.", "aliexpress.", "shein.", "wish.",
    "google.", "bing.", "youtube.",
]


def buscar_google_shopping(client: ApifyClient, queries: list[str], country: str, limit: int) -> list[dict]:
    """Busca produtos no Google Shopping. Retorna items brutos (com merchant + link)."""
    todos = []
    for query in queries:
        print(f"\n  Google Shopping [{country}]: '{query}' (limite: {limit})")
        try:
            run = client.actor("johnvc/google-shopping-api-google-shopping-products-prices-deals").call(
                run_input={
                    "q": query,
                    "gl": country,
                    "hl": {"br": "pt-br", "us": "en", "es": "es"}.get(country, "en"),
                    "max_pages": max(1, -(-limit // 40)),  # ~40 produtos por pagina
                }
            )
            if run["status"] != "SUCCEEDED":
                print(f"    ERRO: {run['status']}")
                continue
            # Um item por pagina; os produtos vem em shopping_results
            items = []
            for pagina in client.dataset(run["defaultDatasetId"]).iterate_items():
                if pagina.get("error_message"):
                    print(f"    ERRO: {pagina['error_message']}")
                    continue
                items.extend(pagina.get("shopping_results") or [])
            items = items[:limit]
            print(f"    {len(items)} produtos")
            todos.extend(items)
        except Exception as e:
            print(f"    ERRO: {e}")
    return todos


def detectar_idioma_simples(html: str, site: str) -> str:
    s = site.lower()
    if ".com.br" in s or s.endswith(".br"):
        return "pt"
    if any(x in s for x in [".mx", ".ar", ".cl", ".co", ".pe", ".es"]):
        return "es"
    if 'lang="pt' in html.lower():
        return "pt"
    return "en"


def extrair_dominio(url: str) -> str | None:
    """Extrai dominio raiz limpo (ex: minhaloja.com.br)."""
    try:
        p = urlparse(url if "://" in url else f"https://{url}")
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except:
        return None


def visitar_site(url: str) -> tuple[str, str] | None:
    """Acessa a homepage e retorna (html, url_final). Retorna None em caso de falha."""
    try:
        r = requests.get(
            url,
            timeout=12,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            allow_redirects=True,
        )
        r.raise_for_status()
        return (r.text, str(r.url))
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", choices=["br", "us", "es", "all"], default="br")
    parser.add_argument("--categoria", choices=["oculos", "roupa", "all"], default="all")
    parser.add_argument("--limit", type=int, default=30, help="Produtos por query no Google Shopping")
    args = parser.parse_args()

    if not APIFY_TOKEN:
        print("ERRO: APIFY_TOKEN nao definido")
        return

    client = ApifyClient(APIFY_TOKEN)

    country_map = {"br": "pt", "us": "en", "es": "es"}
    countries = ["br", "us", "es"] if args.country == "all" else [args.country]
    cats = ["oculos", "roupa"] if args.categoria == "all" else [args.categoria]

    configs = []
    for c in countries:
        idioma = country_map[c]
        for cat in cats:
            queries = SHOPPING_QUERIES.get((cat, idioma), [])
            if queries:
                configs.append((c, cat, queries))

    # Etapa 1: Coleta produtos do Google Shopping
    todos_produtos: list[tuple[dict, str]] = []  # (item, categoria)
    for country, cat, queries in configs:
        items = buscar_google_shopping(client, queries, country, args.limit)
        for item in items:
            todos_produtos.append((item, cat))

    print(f"\n=== {len(todos_produtos)} produtos coletados ===\n")

    # Etapa 2: Filtra por merchant e dominio, agrupa por dominio
    sites_categoria: dict[str, str] = {}  # dominio -> categoria
    sites_merchant: dict[str, str] = {}  # dominio -> merchant name

    for item, cat in todos_produtos:
        merchant = (item.get("source") or "").strip()
        if not merchant or any(b in merchant.lower() for b in BLOCKED_MERCHANTS):
            continue

        # Tenta pegar URL do produto pra extrair dominio
        link = item.get("link") or ""
        dominio = extrair_dominio(link) if link else None
        if not dominio:
            continue
        if any(b in dominio for b in BLOCKED_DOMAINS):
            continue

        if dominio not in sites_categoria:
            sites_categoria[dominio] = cat
            sites_merchant[dominio] = merchant

    print(f"=== {len(sites_categoria)} dominios unicos ===")
    for d in sorted(sites_categoria.keys())[:20]:
        print(f"  - [{sites_categoria[d]}] {d} ({sites_merchant[d]})")
    if len(sites_categoria) > 20:
        print(f"  ... +{len(sites_categoria) - 20} outros")

    # Etapa 3: Acessa cada site e extrai whatsapp + valida
    print(f"\n=== Validando sites ===\n")
    all_leads = []
    seen = set()

    for i, (dominio, cat) in enumerate(sorted(sites_categoria.items()), 1):
        merchant_name = sites_merchant[dominio]
        site = f"https://{dominio}"
        print(f"  [{i}/{len(sites_categoria)}] {merchant_name} ({dominio})...", end=" ")

        if dominio in seen:
            print("ja processado")
            continue
        seen.add(dominio)

        result = visitar_site(site)
        if not result:
            print("FALHA acesso")
            continue

        html, url_final = result

        if not eh_brasileiro(html, url_final):
            print("nao-BR")
            continue

        is_ecom, motivo = eh_ecommerce(html, url_final)
        if not is_ecom:
            print(f"nao-ecom ({motivo})")
            continue

        whatsapp = extrair_whatsapp(html)
        if not whatsapp:
            print("sem-WPP")
            continue

        # Cria lead — instagram pode ficar vazio (nao temos)
        # Usa o dominio como instagram-fallback (pra manter unique)
        lead = {
            "instagram": f"site:{dominio}",  # fallback para nao colidir com unique
            "nome_loja": merchant_name,
            "site": site,
            "seguidores": 0,
            "bio": "",
            "is_business": True,
            "idioma": detectar_idioma_simples(html, url_final),
            "categoria": cat,
            "tem_provador": False,
            "eh_ecommerce": True,
            "whatsapp": whatsapp,
        }
        all_leads.append(lead)
        print(f"OK WPP={whatsapp}")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LEADS_BRUTOS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_leads, f, ensure_ascii=False, indent=2)

    # Salva direto em filtrados tambem (ja validado)
    from config import LEADS_FILTRADOS_PATH
    with open(LEADS_FILTRADOS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_leads, f, ensure_ascii=False, indent=2)

    print(f"\n{len(all_leads)} leads salvos em {LEADS_BRUTOS_PATH}")


if __name__ == "__main__":
    main()
