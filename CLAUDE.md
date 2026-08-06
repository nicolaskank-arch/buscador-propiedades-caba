# CLAUDE.md

Guía para asistentes de IA que trabajen en este repositorio.

> El código, los comentarios y la UI están **en español (rioplatense)**. Mantené ese
> idioma en todo lo que agregues: nombres de funciones, comentarios, prints, labels
> de Streamlit y mensajes de commit.

## Qué es esto

Buscador de departamentos en venta en barrios seleccionados de CABA. Dos piezas:

1. **`argenprop_v01.py`** — scraper CLI de Argenprop. Recorre el listado de venta de
   una lista fija de barrios, extrae las cards, calcula USD/m² y escribe dos CSV.
2. **`dashboard.py`** — dashboard Streamlit que lee los CSV, los unifica, y ofrece
   filtros + gráficos + tabla descargable.

Un workflow de GitHub Actions corre el scraper cada 6 hs y commitea los CSV
actualizados al repo. El dashboard no scrapea: sólo lee los CSV versionados.

## Estructura

```
buscador-propiedades-caba/
├─ argenprop_v01.py             # scraper CLI (BeautifulSoup + rich)
├─ dashboard.py                 # UI Streamlit (pandas + plotly)
├─ argenprop_prueba.csv         # salida FILTRADA (<= --max-usd-m2), la commitea Actions
├─ argenprop_prueba_todas.csv   # salida COMPLETA sin filtrar, la lee el dashboard
├─ requirements.txt
└─ .github/workflows/scrape.yml # cron cada 6 hs + workflow_dispatch
```

No hay `.gitignore`, ni tests, ni linters, ni paquete instalable. Son dos scripts
sueltos en la raíz.

## Comandos

```bash
pip install -r requirements.txt

# Scraper (defaults: --max-usd-m2 2200, --paginas 3, --output argenprop_v01.csv)
python argenprop_v01.py
python argenprop_v01.py --paginas 15 --max-usd-m2 1800 --output argenprop_prueba.csv

# Dashboard (levanta en http://localhost:8501)
streamlit run dashboard.py
```

Python 3.11 (es lo que fija el workflow).

## Contrato de datos: el esquema CSV

Ambos CSV comparten un esquema fijo de 17 columnas, **en este orden**, heredado de
un scraper hermano de MercadoLibre (`ml_barrios_v02`, no está en este repo) para
poder mergear las salidas:

```
fuente, id_aviso, tipo, titulo, barrio, barrio_corto, precio, moneda,
ambientes, dormitorios, banos, metros_cubiertos, metros_totales,
expensas_ars, antiguedad, usd_por_m2, url
```

Reglas que hay que respetar si tocás cualquiera de los dos lados:

- Encoding **`utf-8-sig`** al escribir y al leer (los CSV llevan BOM).
- El orden de columnas sale de las keys del dict `prop` en `extraer_propiedades()`
  (`argenprop_v01.py`) vía `csv.DictWriter(fieldnames=props[0].keys())`. Agregar una
  key ahí cambia el CSV; el dashboard tiene que aguantar la columna nueva.
- `barrio` = dirección completa (`"Calle 123, Sub-barrio, Barrio, Capital Federal"`).
  `barrio_corto` = sólo el barrio. El dashboard parte `barrio` por la primera coma
  para armar la columna `calle`.
- `usd_por_m2` se calcula sólo si `moneda == "USD"` y hay metros > 0. El dashboard
  lo recalcula cuando viene vacío.
- `expensas_ars` sale del texto `"+ $X expensas"` de la card.

### El scraper escribe DOS archivos

`--output X.csv` produce:
- `X_todas.csv` → **todas** las propiedades scrapeadas (esto es lo que consume el dashboard).
- `X.csv` → sólo las que pasan `--max-usd-m2`, ordenadas por USD/m².

No es un typo: el `_todas` se deriva con `args.output.replace(".csv", "_todas.csv")`.

## Cómo funciona el scraper

- URL base: `https://www.argenprop.com/inmuebles/venta/` + barrios unidos con `-o-`.
  La lista `BARRIOS` (20 barrios) está hardcodeada arriba del archivo; paginación con
  `?pagina-N`.
- Selecciona `a.card[data-item-card]` y prefiere los **atributos del card**
  (`montooperacion`, `idmoneda`, `dormitorios`, `ambientes`) por sobre parsear el texto.
  `MONEDA_MAP = {"1": "ARS", "2": "USD"}`; si `idmoneda` no matchea, cae al texto de
  `.card__currency`.
- Corta el loop apenas una página no trae `id_aviso` nuevos (dedup por `id_aviso`).
- `fetch()` reintenta 3 veces con backoff; `sleep_random()` espera 1.5–3 s entre páginas.
  **No bajes esas esperas ni saques el User-Agent** — el sitio bloquea.
- Errores de red no explotan: loguean en amarillo y cortan el loop.

Si Argenprop cambia el markup, lo que se rompe es `extraer_propiedades()`. Los
selectores sensibles: `.card__price`, `.card__currency`, `.card__title--primary`,
`.card__address`, `.card__main-features`, `.card__expenses`.

## Cómo funciona el dashboard

- Lee `ML_CSV = "ml_prueba_todas.csv"` y `AP_CSV = "argenprop_prueba_todas.csv"`.
  **`ml_prueba_todas.csv` no existe en el repo** — el código lo saltea con
  `os.path.exists()`, así que hoy el dashboard corre sólo con datos de Argenprop y
  el filtro "Fuente" muestra un único valor. No borres esa rama: es el hook para
  volver a enchufar MercadoLibre.
- `cargar_datos()` está cacheada con `@st.cache_data(ttl=300)`; los cambios en los CSV
  tardan hasta 5 min en verse.
- `BARRIOS_VALIDOS` (en `dashboard.py`) es una lista **paralela** a `BARRIOS` (en
  `argenprop_v01.py`), pero con espacios en vez de guiones y sin acentos. Si agregás
  un barrio, hay que tocar las dos listas o el barrio cae en `"Sin barrio"` y queda
  fuera del multiselect.
- Columnas derivadas: `m2` (cubiertos → totales), `amb_o_dorm` (ambientes → dormitorios),
  `barrio_norm`, `calle`, `usd_por_m2_valido` (USD y ratio entre 500 y 10.000).

## Automatización (`.github/workflows/scrape.yml`)

- Cron `0 */6 * * *` + `workflow_dispatch` manual.
- Corre `python argenprop_v01.py --paginas 15 --output argenprop_prueba.csv`.
- Commitea `argenprop_prueba.csv` y `argenprop_prueba_todas.csv` como
  `github-actions[bot]` con mensaje `Auto-scrape: YYYY-MM-DD_HH:MM`; si no hay diff,
  no commitea.
- Necesita `permissions: contents: write`.

Consecuencia práctica: **`main` recibe commits automáticos seguido**. Antes de
rebasear o pushear, hacé `git fetch` — el historial se mueve solo. Los commits
`Auto-scrape:` son ruido de datos, no cambios de código.

## Convenciones

- Todo en español, incluidos los comentarios de bloque con separadores
  `# ---------------------------------------------------------------`.
- Salida de consola con `rich` (`console.print`, `Table`, `box.ROUNDED`), no `print()`.
- Nada de f-strings con secretos ni credenciales: este repo no usa ninguna.
- Los CSV **se versionan a propósito** (son el estado de la app). No los agregues a un
  `.gitignore`.
- Al modificar el scraper, verificá contra `argenprop_prueba_todas.csv` que las
  columnas sigan alineadas antes de commitear.

## Trampas conocidas

- `dashboard.py:52` — el `normalizar_barrio()` encadena `.replace().title().replace()`
  para recuperar acentos; es frágil, tocalo con cuidado.
- Los sliders de precio/m² usan `df["precio"].max()` como tope: si el CSV queda vacío
  o sin precios, cae al default (`2000000` / `1000`).
- El filtro `f["usd_por_m2"].fillna(99999) <= usd_m2_max` deja pasar filas sin ratio
  sólo cuando el slider está al máximo.
- El README dice "automatio" (typo por "automático"); no es un nombre de módulo.
