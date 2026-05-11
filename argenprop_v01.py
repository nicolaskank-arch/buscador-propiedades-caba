"""
=====================================================================
  Argenprop Scraper - Barrios CABA + Venta
  Mismo esquema CSV que ml_barrios_v02 para merge posterior
=====================================================================
Requisitos:
    pip install beautifulsoup4 rich

Uso:
    python argenprop_v01.py
    python argenprop_v01.py --max-usd-m2 1800
    python argenprop_v01.py --paginas 5
=====================================================================
"""

import argparse
import csv
import re
import time
import random
import sys
import urllib.request
from urllib.error import HTTPError, URLError

try:
    from bs4 import BeautifulSoup
    from rich.console import Console
    from rich.table import Table
    from rich import box
    console = Console()
except ImportError as e:
    print(f"[ERROR] Falta una dependencia: {e}")
    print("Instalá con:  pip install beautifulsoup4 rich")
    sys.exit(1)


# ---------------------------------------------------------------
#  Configuración
# ---------------------------------------------------------------
BARRIOS = [
    "nunez", "agronomia", "almagro", "barrio-norte",
    "belgrano-chico", "belgrano-r", "belgrano", "belgrano-c",
    "belgrano-barrancas", "botanico", "caballito", "chacarita",
    "coghlan", "colegiales", "palermo", "recoleta", "saavedra",
    "villa-crespo", "villa-urquiza", "puerto-madero",
]

URL_BASE = "https://www.argenprop.com/inmuebles/venta/" + "-o-".join(BARRIOS)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

# idmoneda: 2 = USD (verificado con casos); fallback texto del .card__currency
MONEDA_MAP = {"1": "ARS", "2": "USD"}


# ---------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------
def construir_url(pagina):
    if pagina == 1:
        return URL_BASE
    return f"{URL_BASE}?pagina-{pagina}"


def fetch(url, intentos=3):
    last = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", errors="ignore")
        except (HTTPError, URLError, TimeoutError) as e:
            last = e
            time.sleep(2 + i * 2)
    raise RuntimeError(f"fetch falló: {last}")


def limpiar_numero(texto):
    if texto is None:
        return None
    s = str(texto).replace(".", "").replace(",", ".")
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    return float(nums[0]) if nums else None


def sleep_random():
    time.sleep(random.uniform(1.5, 3.0))


# ---------------------------------------------------------------
#  Extracción de cards
# ---------------------------------------------------------------
def extraer_propiedades(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("a.card[data-item-card]")
    props = []

    for card in cards:
        prop = {
            "fuente":           "argenprop",
            "id_aviso":         card.get("idaviso") or card.get("data-item-card") or "",
            "tipo":             "",
            "titulo":           "",
            "barrio":           "",
            "barrio_corto":     "",
            "precio":           None,
            "moneda":           "",
            "ambientes":        None,
            "dormitorios":      None,
            "banos":            None,
            "metros_cubiertos": None,
            "metros_totales":   None,
            "expensas_ars":     None,
            "antiguedad":       None,
            "usd_por_m2":       None,
            "url":              "",
        }

        # URL
        href = card.get("href", "")
        if href:
            prop["url"] = "https://www.argenprop.com" + href if href.startswith("/") else href

        # Precio + moneda (preferir atributos numéricos del card)
        monto = card.get("montooperacion") or card.get("montonormalizado")
        if monto:
            try:
                prop["precio"] = float(monto)
            except ValueError:
                pass
        idmon = card.get("idmoneda", "")
        if idmon in MONEDA_MAP:
            prop["moneda"] = MONEDA_MAP[idmon]
        else:
            cur = card.select_one(".card__currency")
            if cur:
                txt = cur.get_text(strip=True).upper()
                prop["moneda"] = "USD" if "U" in txt else "ARS" if "$" in txt else ""

        # Fallback de precio desde .card__price si no había atributo
        if prop["precio"] is None:
            p = card.select_one(".card__price")
            if p:
                # primer número grande es el precio principal
                txt = re.sub(r"\+\s*\$[\d\.,]+\s*\n?\s*expensas", "", p.get_text(" ", strip=True), flags=re.I)
                prop["precio"] = limpiar_numero(txt)

        # Dormitorios desde atributo
        d = card.get("dormitorios")
        if d and d.strip().isdigit():
            prop["dormitorios"] = float(d)
        a = card.get("ambientes")
        if a and a.strip().isdigit():
            prop["ambientes"] = float(a)

        # Tipo y barrios desde .card__title--primary
        # Formato observado: "Departamento en Venta en {sub}, {barrio}"  o
        #                    "Departamento en Venta en {barrio}, Capital Federal"
        tp = card.select_one(".card__title--primary")
        if tp:
            txt = tp.get_text(" ", strip=True)
            m = re.match(r"^([A-Za-zÁÉÍÓÚáéíóúÑñ]+)", txt)
            if m:
                prop["tipo"] = m.group(1)
            # Partir por " en " y tomar lo de después del segundo "en"
            partes = re.split(r"\s+en\s+", txt, maxsplit=2)
            if len(partes) >= 3:
                ubicacion = partes[2]
                comps = [c.strip() for c in ubicacion.split(",") if c.strip()]
                comps = [c for c in comps if c.lower() != "capital federal"]
                if comps:
                    main = comps[-1]
                    sub = comps[0]
                    prop["barrio_corto"] = main
                    dirn = card.select_one(".card__address")
                    direccion = dirn.get_text(strip=True) if dirn else ""
                    pieces = [p for p in [direccion, sub if sub != main else None, main, "Capital Federal"] if p]
                    prop["barrio"] = ", ".join(pieces)

        # Título largo (descripción comercial)
        t = card.select_one(".card__title:not(.card__title--primary)")
        if t:
            prop["titulo"] = t.get_text(" ", strip=True)

        # Main features: m², dormitorios, antigüedad
        for li in card.select(".card__main-features li, .card__main-features span"):
            txt = li.get_text(" ", strip=True).lower()
            if not txt:
                continue
            if "m²" in txt or "m2" in txt:
                num = limpiar_numero(txt)
                if "cubie" in txt or "cub." in txt:
                    prop["metros_cubiertos"] = num
                elif "tot" in txt:
                    prop["metros_totales"] = num
                else:
                    if not prop["metros_cubiertos"]:
                        prop["metros_cubiertos"] = num
            elif "dorm" in txt and prop["dormitorios"] is None:
                prop["dormitorios"] = limpiar_numero(txt)
            elif "amb" in txt and prop["ambientes"] is None:
                prop["ambientes"] = limpiar_numero(txt)
            elif "baño" in txt or "bano" in txt:
                prop["banos"] = limpiar_numero(txt)
            elif "año" in txt or "anos" in txt or "antigüe" in txt or "antigue" in txt:
                prop["antiguedad"] = limpiar_numero(txt)
            elif "estrenar" in txt or "a estrenar" in txt:
                prop["antiguedad"] = 0.0

        # Expensas: "+ $2.200.000 expensas" -> 2200000 ARS
        exp = card.select_one(".card__expenses")
        if exp:
            prop["expensas_ars"] = limpiar_numero(exp.get_text(" ", strip=True))

        # USD/m²
        metros = prop["metros_cubiertos"] or prop["metros_totales"]
        if prop["moneda"] == "USD" and prop["precio"] and metros and metros > 0:
            prop["usd_por_m2"] = round(prop["precio"] / metros, 1)

        if prop["url"] or prop["id_aviso"]:
            props.append(prop)

    return props


# ---------------------------------------------------------------
#  Scrape principal
# ---------------------------------------------------------------
def scrape(paginas):
    resultados = []
    vistos = set()
    for pag in range(1, paginas + 1):
        url = construir_url(pag)
        console.print(f"  Página {pag}: {url[:90]}...")
        try:
            html = fetch(url)
        except Exception as e:
            console.print(f"  [yellow]Fallo fetch página {pag}: {e}[/]")
            break

        items = extraer_propiedades(html)
        nuevos = [p for p in items if p["id_aviso"] not in vistos]
        for p in nuevos:
            vistos.add(p["id_aviso"])
        console.print(f"  → {len(items)} cards ({len(nuevos)} únicos nuevos)")
        if not nuevos:
            console.print("  [yellow]Sin resultados nuevos, último page alcanzado.[/]")
            break
        resultados.extend(nuevos)
        sleep_random()
    return resultados


# ---------------------------------------------------------------
#  Filtro + tabla + CSV
# ---------------------------------------------------------------
def filtrar(props, max_usd_m2):
    out = [p for p in props if p["usd_por_m2"] and p["usd_por_m2"] <= max_usd_m2]
    return sorted(out, key=lambda x: x["usd_por_m2"])


def mostrar_tabla(props, max_usd_m2):
    if not props:
        console.print("\n[yellow]Ninguna propiedad pasó el filtro de USD/m².[/]")
        return
    tabla = Table(
        title=f"Argenprop ≤ USD {max_usd_m2:,.0f}/m² — {len(props)} resultados",
        box=box.ROUNDED, show_lines=True,
    )
    tabla.add_column("Tipo",       style="cyan",      width=12)
    tabla.add_column("Barrio",     style="yellow",    width=15)
    tabla.add_column("Dirección",  style="white",     width=25)
    tabla.add_column("USD",        style="yellow",    justify="right", width=10)
    tabla.add_column("m²",         style="blue",      justify="right", width=6)
    tabla.add_column("USD/m²",     style="bold green", justify="right", width=8)
    tabla.add_column("Exp. ARS",   style="white",     justify="right", width=10)
    tabla.add_column("Dorm",       style="white",     justify="right", width=4)
    tabla.add_column("Antig.",     style="white",     justify="right", width=6)
    tabla.add_column("URL",        style="dim",       width=45)

    for p in props:
        ratio = p["usd_por_m2"] or 0
        color = "bold green" if ratio < 1300 else ("yellow" if ratio < 1500 else "white")
        metros = p["metros_cubiertos"] or p["metros_totales"]
        tabla.add_row(
            (p["tipo"]          or "–")[:12],
            (p["barrio_corto"]  or "–")[:15],
            (p["barrio"]        or "–")[:25],
            f"${p['precio']:,.0f}" if p["precio"] else "–",
            f"{metros:.0f}"        if metros       else "–",
            f"[{color}]${ratio:,.0f}[/{color}]",
            f"{p['expensas_ars']:,.0f}" if p["expensas_ars"] else "–",
            f"{int(p['dormitorios'])}"  if p["dormitorios"]  else "–",
            f"{int(p['antiguedad'])}"   if p["antiguedad"] is not None else "–",
            (p["url"] or "")[:45],
        )
    console.print(tabla)


def guardar_csv(props, path):
    if not props:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=props[0].keys())
        writer.writeheader()
        writer.writerows(props)
    console.print(f"\n[bold green]✓ Guardado:[/] {path}  ({len(props)} filas)")


def resumen(filtradas, total, con_ratio):
    ratios = [p["usd_por_m2"] for p in filtradas if p["usd_por_m2"]]
    console.rule("[bold]Resumen Argenprop[/]")
    console.print(f"  Total scrapeadas          : {total}")
    console.print(f"  Con USD/m² calculado      : {con_ratio}")
    console.print(f"  Pasaron el filtro         : [bold green]{len(filtradas)}[/]")
    if ratios:
        console.print(f"  USD/m² promedio (filtr.)  : ${sum(ratios)/len(ratios):,.0f}")
        console.print(f"  USD/m² más bajo           : [bold green]${min(ratios):,.0f}[/]")
    console.rule()


# ---------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Argenprop Scraper - Barrios CABA")
    p.add_argument("--max-usd-m2", type=float, default=2200)
    p.add_argument("--paginas",    type=int,   default=3)
    p.add_argument("--output",     type=str,   default="argenprop_v01.csv")
    return p.parse_args()


def main():
    args = parse_args()

    console.print(f"""
[bold cyan]╔══════════════════════════════════════════════╗
║   ARGENPROP SCRAPER — Barrios CABA           ║
║   Mismo esquema que ml_barrios_v02           ║
╠══════════════════════════════════════════════╣
║  Umbral USD/m²  : {args.max_usd_m2:<7,.0f}                     ║
║  Páginas        : {args.paginas:<28} ║
╚══════════════════════════════════════════════╝[/]
""")
    console.print(f"[dim]Barrios:[/] {', '.join(BARRIOS)}\n")

    todas = scrape(args.paginas)
    con_ratio = sum(1 for p in todas if p["usd_por_m2"])
    console.print(f"\n[bold]Total scrapeadas:[/] {len(todas)} | con USD/m²: {con_ratio}")

    all_path = args.output.replace(".csv", "_todas.csv")
    guardar_csv(todas, all_path)

    filtradas = filtrar(todas, args.max_usd_m2)
    mostrar_tabla(filtradas, args.max_usd_m2)
    resumen(filtradas, len(todas), con_ratio)

    if filtradas:
        guardar_csv(filtradas, args.output)
    else:
        console.print(
            f"\n[yellow]Sin resultados filtrados. Revisá {all_path} para ver qué llegó.[/]"
        )


if __name__ == "__main__":
    main()
