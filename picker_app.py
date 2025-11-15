import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
from PIL import Image
from pyzbar.pyzbar import decode as decode_barcode

# ---------------------------------------
# 🔗 PostgreSQL Connection (same as app.py)
# ---------------------------------------
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

# ---------------------------------------
# 🎨 Page Layout
# ---------------------------------------
st.set_page_config(page_title="Locofly Picker", layout="wide")

st.markdown(
    """
<style>
body { background-color: #F6F8FC; }
.header-box {
    background: linear-gradient(90deg, #4F8BF9, #6CA2F8);
    padding: 20px 24px;
    color: white;
    border-radius: 12px;
    margin-bottom: 20px;
}
.card {
    background: white;
    padding: 18px;
    border-radius: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    margin-bottom: 16px;
}
.stButton>button {
    border-radius: 10px;
    font-weight: 600;
    padding: 10px 24px;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="header-box">
  <h2 style="margin:0;">📦 Locofly Picker</h2>
  <p style="margin:4px 0 0 0;">Scan a product. See bin & quantity instantly.</p>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------
# Helper: given a barcode string, show item & locations
# ---------------------------------------
def show_barcode_info(barcode_value: str):
    barcode_value = barcode_value.strip()
    if not barcode_value:
        st.error("Please scan or type a valid barcode.")
        return

    # 1️⃣ Get item name from barcode_master
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT item_name FROM barcode_master WHERE barcode = :b"),
            {"b": barcode_value},
        ).fetchone()

    if not row:
        st.error(f"❌ Barcode `{barcode_value}` not found in `barcode_master`.")
        return

    item_name = row[0]
    st.success(f"✅ Product: **{item_name}** (Barcode: `{barcode_value}`)")

    # 2️⃣ Fetch all locations where this item exists
    with engine.begin() as conn:
        loc_df = pd.read_sql(
            text(
                """
                SELECT location_id, quantity, updated_at
                FROM inventory
                WHERE item_name = :item
                ORDER BY updated_at DESC
                """
            ),
            conn,
            params={"item": item_name},
        )

    if loc_df.empty:
        st.warning("⚠️ This product is NOT stored in any location yet.")
        return

    st.markdown("### 📦 Stored in These Locations")
    st.dataframe(loc_df, use_container_width=True)

    st.markdown("### ✅ Pick Instructions")
    for row in loc_df.itertuples():
        st.markdown(
            f"- 📍 **Bin:** `{row.location_id}` — **Qty in bin:** `{row.quantity}`"
        )

    st.info("To adjust quantity / move stock, use the main Locofly Inventory app.")


# ---------------------------------------
# 🔍 Picker Workflow
# ---------------------------------------

st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown("## 🔍 Scan / Type Product Barcode")

mode = st.radio(
    "Choose scan method:",
    ["📸 Use Camera", "⌨️ Type / Scanner"],
    horizontal=True,
    label_visibility="collapsed",
)

barcode_string = None

# ========== MODE 1: CAMERA ==========
if mode == "📸 Use Camera":
    st.write("1. Tap below, camera opens. Frame the barcode clearly and click capture.")
    img_file = st.camera_input("Scan using camera")

    if img_file is not None:
        try:
            image = Image.open(img_file)
            decoded_objects = decode_barcode(image)

            if not decoded_objects:
                st.error("Could not detect any barcode in the picture. Try again.")
            else:
                # take the first detected barcode
                barcode_string = decoded_objects[0].data.decode("utf-8")
                st.success(f"Scanned Barcode: `{barcode_string}`")
                # show info immediately
                show_barcode_info(barcode_string)

        except Exception as e:
            st.error(f"Error while decoding barcode: {e}")

# ========== MODE 2: TYPING / SCANNER ==========
else:
    st.write(
        "Keep cursor in this box. Handheld scanner or keyboard will fill the barcode and press Enter / click Search."
    )
    typed_barcode = st.text_input("Scan / type barcode here", key="typed_barcode")

    if st.button("Search / Scan"):
        barcode_string = typed_barcode.strip()
        show_barcode_info(barcode_string)

st.markdown("</div>", unsafe_allow_html=True)
