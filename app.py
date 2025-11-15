import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime

# ======================================================
# 🔗 PostgreSQL Connection
# ======================================================
DB_USER = "suraj"
DB_PASSWORD = "yourpassword"
DB_HOST = "localhost"
DB_NAME = "inventory_db"

engine = create_engine(
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
)

# ======================================================
# 🎨 Page Layout + Styling
# ======================================================
st.set_page_config(page_title="Locofly Inventory System", layout="wide")

st.markdown("""
<style>

body { background-color: #F6F8FC; }

.sidebar .sidebar-content {
    background-color: #ffffff;
    border-right: 1px solid #E0E6ED;
}

.header-box {
    background: linear-gradient(90deg, #4F8BF9, #6CA2F8);
    padding: 22px 28px;
    color: white;
    border-radius: 10px;
    margin-bottom: 25px;
}

.card {
    background: white;
    padding: 25px;
    border-radius: 14px;
    box-shadow: 0px 1px 3px rgba(0,0,0,0.08);
    margin-bottom: 25px;
}

input, textarea { border-radius: 10px !important; }

.stButton>button {
    border-radius: 8px;
    font-weight: 600;
    padding: 8px 20px;
}

</style>
""", unsafe_allow_html=True)


# ======================================================
# 📌 Load All Locations
# ======================================================
def get_all_locations():
    with engine.begin() as conn:
        result = conn.execute(
            text("SELECT DISTINCT location_id FROM inventory ORDER BY location_id")
        )
        return [row[0] for row in result]


locations = get_all_locations()


# ======================================================
# 🔍 QR Auto-Select Logic
# ======================================================
query_params = st.query_params

qr_loc = None
qr_item = None
sidebar_enabled = True

if "loc" in query_params:
    qr_loc = query_params["loc"]
    if isinstance(qr_loc, list):  
        qr_loc = qr_loc[0]

    if qr_loc in locations:
        sidebar_enabled = False  # hide sidebar when loaded by QR

if "item" in query_params:
    qr_item = query_params["item"]
    if isinstance(qr_item, list):
        qr_item = qr_item[0]


# ======================================================
# HEADER
# ======================================================
st.markdown("""
<div class="header-box">
    <h1 style="margin:0; font-size:34px;">📦 Locofly Inventory System</h1>
    <p style="margin-top:6px; margin-bottom:0; font-size:16px; opacity:0.95;">
        Fast. Simple. Reliable. Track your stock in real-time.
    </p>
</div>
""", unsafe_allow_html=True)



# ======================================================
# 🔍 PICKER VIEW — Scan Product Barcode
# ======================================================
st.markdown("## 🔍 Picker View – Scan Product Barcode")

barcode_input = st.text_input("Scan / Type Product Barcode")

if st.button("Search Barcode"):

    if not barcode_input.strip():
        st.error("Please scan or type a valid barcode.")
        st.stop()

    # 1️⃣ Fetch item name
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT item_name FROM barcode_master WHERE barcode = :b"),
            {"b": barcode_input.strip()}
        ).fetchone()

    if not row:
        st.error("❌ Barcode not found in barcode_master.")
        st.stop()

    item_name_from_code = row[0]
    st.success(f"Product Found: **{item_name_from_code}**")

    # 2️⃣ Fetch all locations containing this item
    with engine.begin() as conn:
        loc_df = pd.read_sql(
            text("""
                SELECT location_id, quantity, updated_at
                FROM inventory
                WHERE item_name = :item
                ORDER BY updated_at DESC
            """),
            conn,
            params={"item": item_name_from_code}
        )

    if loc_df.empty:
        st.warning("⚠️ This product is NOT stored in any location yet.")
        st.stop()

    st.markdown("### 📦 Stored in These Locations:")
    st.dataframe(loc_df, use_container_width=True)

    st.markdown("### 👉 Tap a Location to Open")
    for row in loc_df.itertuples():
        L = row.location_id
        st.markdown(f"- 🔗 [Open {L}](?loc={L}&item={item_name_from_code})")



# ======================================================
# 📍 SIDEBAR — Only if NOT QR navigation
# ======================================================
if sidebar_enabled:
    st.sidebar.header("📍 Location Manager")

    selected_loc = st.sidebar.selectbox("Select Location", ["(Create New)"] + locations)

    new_loc = st.sidebar.text_input("Enter new location_id")

    if st.sidebar.button("Create Location"):
        if not new_loc.strip():
            st.sidebar.error("Location ID cannot be blank")
        else:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                        VALUES (:loc, '', 0, :ts)
                        ON CONFLICT DO NOTHING
                    """),
                    {"loc": new_loc.strip(), "ts": datetime.now()}
                )
            st.sidebar.success(f"Location '{new_loc}' created.")
            st.rerun()

else:
    selected_loc = qr_loc


# If STILL nothing selected → stop
if not selected_loc:
    st.info("Scan a QR code or select a location from sidebar.")
    st.stop()

loc = selected_loc



# ======================================================
# 🧾 ITEMS IN LOCATION
# ======================================================
st.markdown(f"<div class='card'><h3>📍 Location: <code>{loc}</code></h3>", unsafe_allow_html=True)

with engine.begin() as conn:
    items_df = pd.read_sql(
        text("""
            SELECT item_name, quantity, updated_at
            FROM inventory
            WHERE location_id = :loc AND item_name <> ''
            ORDER BY item_name
        """),
        conn,
        params={"loc": loc}
    )

st.dataframe(items_df, use_container_width=True)
st.markdown("</div>", unsafe_allow_html=True)


# ======================================================
# 🛠 ADD / UPDATE ITEM
# ======================================================
st.markdown("<div class='card'><h3>🛠 Add / Update Item</h3>", unsafe_allow_html=True)

# Pre-fill item name when opened from barcode picker
default_item = qr_item if qr_item else ""

item_name = st.text_input("Item Name", value=default_item, key="item_input")
quantity = st.number_input("Quantity", step=1, min_value=0, key="qty_input")

c1, c2 = st.columns([1,1])

with c1:
    if st.button("Save / Update", type="primary"):
        if not item_name.strip():
            st.error("Item name cannot be blank.")
        else:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                        VALUES (:loc, :item, :qty, :ts)
                        ON CONFLICT (location_id, item_name)
                        DO UPDATE SET quantity = :qty, updated_at = :ts
                    """),
                    {"loc": loc, "item": item_name.strip(), "qty": quantity, "ts": datetime.now()}
                )
            st.success(f"Item '{item_name}' saved/updated.")
            st.rerun()

with c2:
    if st.button("Delete Item"):
        if not item_name.strip():
            st.error("Enter item name to delete.")
        else:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM inventory WHERE location_id = :loc AND item_name = :item"),
                    {"loc": loc, "item": item_name.strip()}
                )
            st.warning(f"Item '{item_name}' deleted.")
            st.rerun()

st.markdown("</div>", unsafe_allow_html=True)