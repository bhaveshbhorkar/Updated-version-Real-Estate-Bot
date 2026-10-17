import os
import random
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="EstateIQ", layout="wide")
st.markdown("<style>.block-container{padding-top:1.4rem;max-width:1200px}</style>", unsafe_allow_html=True)

HOST = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
ENDPOINT = os.environ.get("SERVING_ENDPOINT", "")
WAREHOUSE = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
if HOST and not HOST.startswith("http"):
    HOST = "https://" + HOST
MAX_Q = 20
QUICK = ["Maximum price in Ahmedabad?", "Top localities in Pune?", "Most in-demand property type?"]
AMBER, SKY = "#ffb547", "#7c8cff"


# ---------- hero: animated skyline ----------
def skyline():
    rnd, x, out = random.Random(7), 0, []
    while x < 1600:
        w, bh = rnd.randint(50, 110), rnd.randint(60, 220)
        y = 260 - bh
        g = [f'<g class="b" style="--d:{x / 1600 * 0.9:.2f}s"><rect x="{x}" y="{y}" width="{w}" height="{bh}" fill="#080d22"/>']
        for wy in range(y + 12, 250, 16):
            for wx in range(x + 8, x + w - 10, 14):
                if rnd.random() < 0.34:
                    g.append(f'<rect x="{wx}" y="{wy}" width="6" height="8" fill="{AMBER}" opacity="{0.5 + rnd.random() * 0.5:.2f}"/>')
        g.append("</g>")
        out.append("".join(g))
        x += w + rnd.randint(0, 8)
    return "".join(out)


HERO = """<style>
body{margin:0;font-family:system-ui,sans-serif}
.h{position:relative;height:300px;overflow:hidden;border-radius:18px;background:linear-gradient(180deg,#0b1026,#16224d 60%,#2a3a72);color:#fff}
h1{position:absolute;z-index:2;left:36px;top:32px;margin:0;font-size:clamp(30px,5vw,52px);line-height:1.02;max-width:600px}
p{position:absolute;z-index:2;left:36px;top:150px;margin:0;color:#c5cdf0;font-size:18px;max-width:430px}
svg{position:absolute;left:0;bottom:0;width:100%;height:58%}
.b{transform-origin:center bottom;transform-box:fill-box;animation:rise 1s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--d)}
@keyframes rise{from{transform:scaleY(0)}}
@media(prefers-reduced-motion:reduce){.b{animation:none}}
</style>
<div class="h"><h1>Ask the market, not a spreadsheet.</h1>
<p>Explore prices, localities and demand, then ask the assistant anything.</p>
<svg viewBox="0 0 1600 260" preserveAspectRatio="xMidYMax slice">__SKY__</svg></div>"""
components.html(HERO.replace("__SKY__", skyline()), height=310)


# ---------- data ----------
NUMERIC = {"BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL"}


@st.cache_data(ttl=600, show_spinner="Reading live data from Databricks. This can take a minute if the warehouse is starting.")
def query(table):
    h = {"Authorization": f"Bearer {TOKEN}"}
    r = requests.post(f"{HOST}/api/2.0/sql/statements", headers=h, timeout=60, json={
        "warehouse_id": WAREHOUSE, "statement": f"SELECT * FROM workspace.semantic.{table}",
        "wait_timeout": "50s", "on_wait_timeout": "CONTINUE"})
    r.raise_for_status()
    j, t0 = r.json(), time.time()
    while j["status"]["state"] in ("PENDING", "RUNNING") and time.time() - t0 < 180:
        time.sleep(3)
        j = requests.get(f"{HOST}/api/2.0/sql/statements/{j['statement_id']}", headers=h, timeout=60).json()
    if j["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(j["status"].get("error", {}).get("message", j["status"]["state"]))
    cols = j["manifest"]["schema"]["columns"]
    df = pd.DataFrame(j.get("result", {}).get("data_array", []), columns=[c["name"] for c in cols])
    for c in cols:
        if c["type_name"] in NUMERIC:
            df[c["name"]] = pd.to_numeric(df[c["name"]])
    return df


def get(name, table):
    live_err = None
    if HOST and TOKEN and WAREHOUSE:
        try:
            return query(table)
        except Exception as e:
            live_err = str(e)[:200]
    try:
        return pd.read_csv(f"data/{name}.csv")
    except Exception:
        raise RuntimeError(live_err or "DATABRICKS_WAREHOUSE_ID is not set and there are no CSV files.")


ready, load_err = True, ""
try:
    price = get("avg_price_by_city", "avg_price_by_city_metrics")
    locs = get("top_selling_locations", "top_selling_locations_metrics")
    props = get("property_type_demand", "property_type_demand_metrics")
    props = props.assign(sell_through=(props["total_units_sold"] / props["total_listing_count"] * 100).round(1))
except Exception as e:
    ready, load_err = False, str(e)


def style(fig, h=420):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=0, r=0, t=40, b=0), height=h, title_font_size=18)
    return fig


tab1, tab2 = st.tabs(["Explore the market", "Ask the assistant"])


# ---------- tab 1: interactive charts (live from Databricks) ----------
def charts():
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cities", locs["city"].nunique())
    c2.metric("Localities", f"{len(locs):,}")
    c3.metric("Units sold", f"{int(props['total_units_sold'].sum()):,}")
    c4.metric("Overall sell-through", f"{props['total_units_sold'].sum() / props['total_listing_count'].sum() * 100:.1f}%")
    st.subheader("Prices by city")
    num = price.select_dtypes("number").columns.tolist()
    cat = next((c for c in price.columns if c not in num), price.columns[0])
    if num:
        a, b = st.columns([1, 2])
        metric = a.selectbox("Measure", num)
        picked = b.multiselect("Cities (empty shows all)", sorted(price[cat].astype(str).unique()))
        d = price if not picked else price[price[cat].astype(str).isin(picked)]
        d = d.sort_values(metric, ascending=False)
        fig = px.bar(d, x=cat, y=metric, color=metric, color_continuous_scale=["#3b4a9a", AMBER])
        st.plotly_chart(style(fig).update_coloraxes(showscale=False), use_container_width=True)
    else:
        st.dataframe(price, use_container_width=True)

    st.subheader("Best selling localities")
    a, b, c = st.columns([1, 1, 1])
    city = a.selectbox("City", ["All"] + sorted(locs["city"].unique()))
    top_n = b.slider("Show top", 5, 30, 12)
    view = c.radio("View", ["Bars", "Treemap"], horizontal=True)
    d = locs if city == "All" else locs[locs["city"] == city]
    if view == "Treemap":
        fig = px.treemap(d, path=["city", "locality"], values="total_units_sold", color="total_units_sold",
                         color_continuous_scale=["#3b4a9a", AMBER])
        st.plotly_chart(style(fig, 460).update_coloraxes(showscale=False), use_container_width=True)
    else:
        d = d.nlargest(top_n, "total_units_sold").assign(place=lambda x: x["locality"] + ", " + x["city"])
        fig = px.bar(d.sort_values("total_units_sold"), x="total_units_sold", y="place", orientation="h",
                     color="city" if city == "All" else None, color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(style(fig, 460).update_layout(yaxis_title=None), use_container_width=True)

    st.subheader("Property type demand")
    a, b = st.columns(2)
    fig = px.bar(props.melt("property_type", ["total_listing_count", "total_units_sold"]), x="property_type",
                 y="value", color="variable", barmode="group", color_discrete_sequence=[SKY, AMBER])
    a.plotly_chart(style(fig, 380).update_layout(legend_title=None), use_container_width=True)
    fig = px.pie(props, names="property_type", values="total_units_sold", hole=0.55,
                 color_discrete_sequence=px.colors.qualitative.Pastel)
    b.plotly_chart(style(fig, 380), use_container_width=True)
    fig = px.scatter(props, x="total_listing_count", y="total_units_sold", size="sell_through", color="property_type",
                     hover_data=["sell_through"], size_max=45, color_discrete_sequence=px.colors.qualitative.Pastel)
    st.plotly_chart(style(fig, 360), use_container_width=True)


# ---------- tab 2: chat with the Databricks supervisor agent ----------
def ask_agent(messages):
    r = requests.post(
        f"{HOST}/serving-endpoints/{ENDPOINT}/invocations",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        json={"input": messages[-10:]}, timeout=240)
    if r.status_code != 200:
        raise RuntimeError(f"Request failed ({r.status_code})")
    data = r.json()
    texts = [c.get("text", "") for i in data.get("output", []) if i.get("type") == "message"
             for c in i.get("content", []) if c.get("type") == "output_text"]
    if texts:
        return texts[-1]
    if "choices" in data:
        return data["choices"][0]["message"]["content"]
    return "Sorry, I could not find an answer."


with tab2:
    if not (HOST and TOKEN and ENDPOINT):
        st.info("The assistant is not connected yet. Add the Databricks secrets to turn it on.")
    else:
        st.session_state.setdefault("msgs", [])
        st.session_state.setdefault("count", 0)
        for m in st.session_state.msgs:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        for col, q in zip(st.columns(len(QUICK)), QUICK):
            if col.button(q, use_container_width=True):
                st.session_state.pending = q
        prompt = st.chat_input("Ask about prices, localities or property types") or st.session_state.pop("pending", None)
        if prompt:
            if st.session_state.count >= MAX_Q:
                st.warning("Question limit reached for this session. Refresh the page to continue.")
            else:
                st.session_state.count += 1
                st.session_state.msgs.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant"):
                    with st.spinner("Looking at the market data. The first answer can take up to a minute."):
                        try:
                            answer = ask_agent(st.session_state.msgs)
                        except Exception as e:
                            answer = f"The assistant could not answer right now. {e}"
                    st.markdown(answer)
                st.session_state.msgs.append({"role": "assistant", "content": answer})


with tab1:
    if ready:
        charts()
    else:
        st.warning(f"The charts could not load the data: {load_err}")
