"""
Dashboard de propiedades - ML + Argenprop
Usar:
    streamlit run dashboard.py
"""
import os
import re
import unicodedata
import pandas as pd
import streamlit as st
import plotly.express as px

# ---------------------------------------------------------------
#  Config
# ---------------------------------------------------------------
st.set_page_config(
    page_title="Buscador de Propiedades CABA",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSV inputs (raw, sin filtrar)
ML_CSV = "ml_prueba_todas.csv"
AP_CSV = "argenprop_prueba_todas.csv"

# Barrios "verdaderos" (los que tienen sentido como barrio CABA)
BARRIOS_VALIDOS = {
    "nunez","agronomia","almagro","barrio norte","belgrano chico",
    "belgrano r","belgrano","belgrano c","belgrano barrancas","botanico",
    "caballito","chacarita","coghlan","colegiales","palermo",
    "recoleta","saavedra","villa crespo","villa urquiza","puerto madero",
}


# ---------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------
def slugify(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.lower().strip()


def normalizar_barrio(b):
    if not isinstance(b, str):
        return "Sin barrio"
    slug = slugify(b)
    if slug in BARRIOS_VALIDOS:
        # Capitalizar bonito
        return slug.replace("nunez","Núñez").replace("botanico","Botánico").title().replace("Núñez","Núñez").replace("Botánico","Botánico")
    return "Sin barrio"


@st.cache_data(ttl=300)
def cargar_datos():
    """Lee ML + Argenprop, normaliza y devuelve un DataFrame unificado."""
    dfs = []

    if os.path.exists(ML_CSV):
        df_ml = pd.read_csv(ML_CSV, encoding="utf-8-sig")
        df_ml["fuente"] = "MercadoLibre"
        for col in ["dormitorios","expensas_ars","antiguedad","id_aviso"]:
            if col not in df_ml.columns:
                df_ml[col] = None
        # ID extraído de URL ML-XXX
        df_ml["id_aviso"] = df_ml["url"].astype(str).str.extract(r"MLA-(\d+)")[0]
        dfs.append(df_ml)

    if os.path.exists(AP_CSV):
        df_ap = pd.read_csv(AP_CSV, encoding="utf-8-sig")
        df_ap["fuente"] = "Argenprop"
        dfs.append(df_ap)

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True, sort=False)

    # Tipos numéricos
    for col in ["precio","ambientes","dormitorios","banos","metros_cubiertos",
                "metros_totales","expensas_ars","antiguedad","usd_por_m2"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Métricas derivadas
    df["m2"] = df["metros_cubiertos"].fillna(df["metros_totales"])
    df["amb_o_dorm"] = df["ambientes"].fillna(df["dormitorios"])

    # Recalcular usd_por_m2 cuando falte
    mask = df["usd_por_m2"].isna() & (df["moneda"] == "USD") & df["precio"].notna() & df["m2"].notna() & (df["m2"] > 0)
    df.loc[mask, "usd_por_m2"] = (df.loc[mask, "precio"] / df.loc[mask, "m2"]).round(1)

    # Normalizar barrio
    df["barrio_norm"] = df["barrio_corto"].apply(normalizar_barrio)

    # Calle limpia (primer fragmento antes de la primera coma)
    df["calle"] = df["barrio"].astype(str).str.split(",").str[0].str.strip()

    # Filtro de outliers obvios
    df["usd_por_m2_valido"] = (
        df["usd_por_m2"].between(500, 10000) & (df["moneda"] == "USD")
    )

    return df


# ---------------------------------------------------------------
#  UI
# ---------------------------------------------------------------
st.title("🏠 Buscador de Propiedades CABA")
st.caption("Datos combinados de MercadoLibre + Argenprop")

df = cargar_datos()
if df.empty:
    st.error("No encontré los CSVs. Asegurate de tener ml_prueba_todas.csv y/o argenprop_prueba_todas.csv en el mismo directorio.")
    st.stop()

# ---------- Sidebar: filtros ----------
st.sidebar.header("Filtros")

fuentes = st.sidebar.multiselect(
    "Fuente",
    options=sorted(df["fuente"].unique()),
    default=sorted(df["fuente"].unique()),
)

barrios_opts = sorted([b for b in df["barrio_norm"].unique() if b != "Sin barrio"])
barrios_sel = st.sidebar.multiselect(
    "Barrios",
    options=barrios_opts,
    default=barrios_opts,
)

tipos_opts = sorted(df["tipo"].dropna().unique().tolist())
tipos_sel = st.sidebar.multiselect("Tipo", options=tipos_opts, default=tipos_opts)

precio_min, precio_max = st.sidebar.slider(
    "Precio (USD)",
    min_value=0,
    max_value=int(df["precio"].max() or 2000000),
    value=(0, 500000),
    step=10000,
    format="$%d",
)

m2_min, m2_max = st.sidebar.slider(
    "m² cubiertos",
    min_value=0,
    max_value=int(df["m2"].max() or 1000),
    value=(0, 300),
    step=5,
)

usd_m2_max = st.sidebar.slider(
    "USD/m² máximo",
    min_value=500,
    max_value=10000,
    value=10000,
    step=100,
    format="$%d",
)

amb_min = st.sidebar.number_input("Ambientes/dorm. mínimo", min_value=0, max_value=10, value=0)

solo_validos = st.sidebar.checkbox("Sólo USD/m² razonable (500-10k)", value=True)

# ---------- Aplicar filtros ----------
f = df[df["fuente"].isin(fuentes)].copy()
f = f[f["barrio_norm"].isin(barrios_sel)]
f = f[f["tipo"].isin(tipos_sel)]
f = f[(f["precio"].fillna(0) >= precio_min) & (f["precio"].fillna(0) <= precio_max)]
f = f[(f["m2"].fillna(0) >= m2_min) & (f["m2"].fillna(0) <= m2_max)]
f = f[f["usd_por_m2"].fillna(99999) <= usd_m2_max]
f = f[f["amb_o_dorm"].fillna(0) >= amb_min]
if solo_validos:
    f = f[f["usd_por_m2_valido"]]

# ---------- KPI cards ----------
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Propiedades", f"{len(f):,}", f"{len(f)-len(df):+,} vs total")
col2.metric("USD/m² promedio", f"${f['usd_por_m2'].mean():,.0f}" if len(f) else "–")
col3.metric("Mínimo USD/m²", f"${f['usd_por_m2'].min():,.0f}" if len(f) else "–")
col4.metric("Precio promedio", f"${f['precio'].mean():,.0f}" if len(f) else "–")
col5.metric("m² promedio", f"{f['m2'].mean():,.0f}" if len(f) else "–")

st.divider()

# ---------- Charts ----------
g1, g2 = st.columns(2)

with g1:
    st.subheader("USD/m² promedio por barrio")
    barrio_stats = (
        f.dropna(subset=["usd_por_m2"])
         .groupby("barrio_norm")
         .agg(prom=("usd_por_m2", "mean"), n=("usd_por_m2", "count"))
         .reset_index()
         .sort_values("prom")
    )
    if len(barrio_stats):
        fig = px.bar(
            barrio_stats,
            x="prom", y="barrio_norm", orientation="h",
            text=barrio_stats["prom"].round().astype(int).map("${:,}".format),
            hover_data=["n"],
            labels={"prom": "USD/m²", "barrio_norm": "", "n": "cant."},
            color="prom",
            color_continuous_scale="RdYlGn_r",
        )
        fig.update_layout(height=480, coloraxis_showscale=False, margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos para graficar con estos filtros")

with g2:
    st.subheader("Precio vs m² (color = USD/m²)")
    if len(f):
        fig = px.scatter(
            f.dropna(subset=["precio","m2","usd_por_m2"]),
            x="m2", y="precio",
            color="usd_por_m2",
            hover_data=["barrio_norm","tipo","calle","amb_o_dorm","antiguedad"],
            color_continuous_scale="RdYlGn_r",
            labels={"m2": "m²", "precio": "USD", "usd_por_m2": "USD/m²"},
        )
        fig.update_layout(height=480, margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos")

st.divider()

# ---------- Tabla ----------
st.subheader(f"Listado de {len(f)} propiedades")

orden = st.selectbox(
    "Ordenar por",
    options=["usd_por_m2 (mejor primero)", "precio (menor primero)", "precio (mayor primero)", "m2 (mayor primero)"],
)
sort_map = {
    "usd_por_m2 (mejor primero)": ("usd_por_m2", True),
    "precio (menor primero)": ("precio", True),
    "precio (mayor primero)": ("precio", False),
    "m2 (mayor primero)": ("m2", False),
}
col, asc = sort_map[orden]

cols_show = [
    "fuente","barrio_norm","tipo","calle","precio","moneda",
    "m2","usd_por_m2","amb_o_dorm","banos","expensas_ars","antiguedad","url",
]
tabla = f.sort_values(col, ascending=asc, na_position="last")[cols_show].rename(columns={
    "fuente":"Fuente",
    "barrio_norm":"Barrio",
    "tipo":"Tipo",
    "calle":"Dirección",
    "precio":"Precio",
    "moneda":"Moneda",
    "m2":"m²",
    "usd_por_m2":"USD/m²",
    "amb_o_dorm":"Amb/Dorm",
    "banos":"Baños",
    "expensas_ars":"Expensas ARS",
    "antiguedad":"Antig.",
    "url":"Link",
})

st.dataframe(
    tabla,
    use_container_width=True,
    hide_index=True,
    height=520,
    column_config={
        "Precio": st.column_config.NumberColumn(format="$%d"),
        "USD/m²": st.column_config.NumberColumn(format="$%d"),
        "Expensas ARS": st.column_config.NumberColumn(format="$%d"),
        "m²": st.column_config.NumberColumn(format="%d"),
        "Amb/Dorm": st.column_config.NumberColumn(format="%d"),
        "Baños": st.column_config.NumberColumn(format="%d"),
        "Antig.": st.column_config.NumberColumn(format="%d"),
        "Link": st.column_config.LinkColumn(display_text="abrir →"),
    },
)

# Download
csv_bytes = tabla.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "⬇️ Descargar CSV de la vista filtrada",
    data=csv_bytes,
    file_name="propiedades_filtradas.csv",
    mime="text/csv",
)

st.caption("Datos de MercadoLibre + Argenprop. Última carga al iniciar la app (5 min cache).")
