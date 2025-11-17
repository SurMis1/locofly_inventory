import os
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text


# ==========================================
# DB connection
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    st.stop()

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# ==========================================
# Page layout / CSS
# ==========================================
st.set_page_config(
    page_title="Locofly Inventory System",
    layout="wide",
)

st.markdown(
    """
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
    padding: 22px;
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
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="header-box">
  <h1 style="margin:0; font-size:34px;">📦 Locofly Inventory System</h1>
  <p style="margin-top:6px; margin-bottom:0; font-size:16px; opacity:0.95;">
      Fast. Simple. Reliable. Track your stock in real-time.
  </p>
</div>
""",
    unsafe_allow_html=True,
)


# ==========================================
# Helpers
# ==========================================

CREATE_NEW_LABEL = "(Create New)"


def get_all_locations() -> list[int]:
    """Return list of distinct location_ids (ints)."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT location_id "
                "FROM inventory "
                "ORDER BY location_id"
            )
        ).fetchall()
    return [int(r[0]) for r in rows]


def get_items_for_location(location_id: int) -> pd.DataFrame:
    """Return all items for a location, including barcodes."""
    with engine.begin() as conn:
        df = pd.read_sql(
            text(
                """
                SELECT i.item_name,
                       i.quantity,
                       i.updated_at,
                       b.barcode
                FROM inventory i
                LEFT JOIN barcode_master b
                       ON b.item_name = i.item_name
                WHERE i.location_id = :loc
                  AND i.item_name <> ''
                ORDER BY i.item_name
                """
            ),
            conn,
            params={"loc": location_id},
        )
    return df


def upsert_inventory(location_id: int, item_name: str, quantity: int):
    """Insert / update inventory and log change."""
    item_name = item_name.strip()
    ts = datetime.now()

    with engine.begin() as conn:
        old = conn.execute(
            text(
                """
                SELECT quantity
                FROM inventory
                WHERE location_id = :loc
                  AND item_name = :item
                """
            ),
            {"loc": location_id, "item": item_name},
        ).scalar()

        if old is None:
            action = "insert"
            old_qty = None
        else:
            action = "update"
            old_qty = int(old)

        conn.execute(
            text(
                """
                INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                VALUES (:loc, :item, :qty, :ts)
                ON CONFLICT (location_id, item_name)
                DO UPDATE SET quantity = :qty, updated_at = :ts
                """
            ),
            {"loc": location_id, "item": item_name, "qty": quantity, "ts": ts},
        )

        conn.execute(
            text(
                """
                INSERT INTO inventory_log
                    (location_id, item_name, old_quantity, new_quantity, action, action_time)
                VALUES
                    (:loc, :item, :old_qty, :new_qty, :action, :ts)
                """
            ),
            {
                "loc": location_id,
                "item": item_name,
                "old_qty": old_qty,
                "new_qty": quantity,
                "action": action,
                "ts": ts,
            },
        )


def delete_inventory_item(location_id: int, item_name: str):
    """Delete one item from inventory and log."""
    item_name = item_name.strip()
    ts = datetime.now()

    with engine.begin() as conn:
        old = conn.execute(
            text(
                """
                SELECT quantity
                FROM inventory
                WHERE location_id = :loc
                  AND item_name = :item
                """
            ),
            {"loc": location_id, "item": item_name},
        ).scalar()

        conn.execute(
            text(
                """
                DELETE FROM inventory
                WHERE location_id = :loc
                  AND item_name = :item
                """
            ),
            {"loc": location_id, "item": item_name},
        )

        if old is not None:
            conn.execute(
                text(
                    """
                    INSERT INTO inventory_log
                        (location_id, item_name, old_quantity, new_quantity, action, action_time)
                    VALUES
                        (:loc, :item, :old_qty, 0, 'delete', :ts)
                    """
                ),
                {"loc": location_id, "item": item_name, "old_qty": int(old), "ts": ts},
            )


def get_shortage_report(threshold: int = 1) -> pd.DataFrame:
    with engine.begin() as conn:
        df = pd.read_sql(
            text(
                """
                SELECT location_id, item_name, quantity, updated_at
                FROM inventory
                WHERE quantity <= :th
                ORDER BY quantity, updated_at
                """
            ),
            conn,
            params={"th": threshold},
        )
    return df


# ==========================================
# Query params (for barcode picker / QR links)
# ==========================================
q = st.query_params

qr_loc = None
qr_item = None
sidebar_enabled = True

if "loc" in q:
    qr_loc_raw = q["loc"]
    if isinstance(qr_loc_raw, list):
        qr_loc_raw = qr_loc_raw[0]
    try:
        qr_loc = int(qr_loc_raw)
        sidebar_enabled = False
    except ValueError:
        qr_loc = None

if "item" in q:
    qr_item_raw = q["item"]
    if isinstance(qr_item_raw, list):
        qr_item_raw = qr_item_raw[0]
    qr_item = qr_item_raw


# ==========================================
# Sidebar – Location Manager
# ==========================================
all_locations = get_all_locations()

if "item_input" not in st.session_state:
    st.session_state["item_input"] = qr_item or ""
if "qty_input" not in st.session_state:
    st.session_state["qty_input"] = 0

if sidebar_enabled:
    st.sidebar.header("📍 Location Manager")

    options = [CREATE_NEW_LABEL] + [str(l) for l in all_locations]
    selected_label = st.sidebar.selectbox("Select Location", options)

    if selected_label == CREATE_NEW_LABEL:
        selected_location = None
    else:
        selected_location = int(selected_label)

    new_loc_text = st.sidebar.text_input(
        "Enter new location_id (number)", key="new_loc"
    )

    if st.sidebar.button("Create Location"):
        if not new_loc_text.strip().isdigit():
            st.sidebar.error("Location ID must be a number (e.g. 1, 2, 101).")
        else:
            new_loc = int(new_loc_text.strip())
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                        VALUES (:loc, '', 0, :ts)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"loc": new_loc, "ts": datetime.now()},
                )
            st.sidebar.success(f"Location {new_loc} created.")
            st.rerun()
else:
    # When coming from QR / barcode link
    selected_location = qr_loc

if not selected_location:
    loc_display = CREATE_NEW_LABEL
else:
    loc_display = str(selected_location)


# ==========================================
# 1. Picker View – Barcode based workflow
# ==========================================
st.markdown("## 🔍 Picker View – Scan Product Barcode")

barcode_input = st.text_input("Scan / Type Product Barcode", key="barcode_box")

if st.button("Search Barcode"):
    if not barcode_input.strip():
        st.error("Please scan or type a valid barcode.")
    else:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT item_name
                    FROM barcode_master
                    WHERE barcode = :b
                    """
                ),
                {"b": barcode_input.strip()},
            ).fetchone()

        if not row:
            st.error("❌ Barcode not found in barcode_master.")
        else:
            item_name_from_code = row[0]
            st.success(f"Product found: **{item_name_from_code}**")

            with engine.begin() as conn:
                loc_df = pd.read_sql(
                    text(
                        """
                        SELECT location_id, quantity, updated_at
                        FROM inventory
                        WHERE item_name = :item
                          AND item_name <> ''
                        ORDER BY updated_at DESC
                        """
                    ),
                    conn,
                    params={"item": item_name_from_code},
                )

            if loc_df.empty:
                st.warning("This product is not stored in any location yet.")
            else:
                st.markdown("### 📦 Stored in these locations")
                st.dataframe(loc_df, use_container_width=True)

                st.markdown("### 👉 Tap a location to open it")
                for r in loc_df.itertuples():
                    loc_id = int(r.location_id)
                    label = f"Open location {loc_id} (qty {r.quantity})"
                    if st.button(label, key=f"open_loc_{loc_id}"):
                        st.query_params["loc"] = str(loc_id)
                        st.query_params["item"] = item_name_from_code
                        st.rerun()


# ==========================================
# 2. Location detail + tap-to-edit
# ==========================================
st.markdown("## 📍 Location View")

st.markdown(
    f"<div class='card'><h3>📍 Location: <code>{loc_display}</code></h3>",
    unsafe_allow_html=True,
)

if selected_location is None:
    st.info("Select an existing location or create a new one from the sidebar.")
    st.markdown("</div>", unsafe_allow_html=True)
else:
    items_df = get_items_for_location(selected_location)

    if items_df.empty:
        st.write("No items in this location yet.")
    else:
        st.markdown("### Current items (tap Edit to modify)")
        st.dataframe(items_df, use_container_width=True)

        st.markdown("#### Quick edit buttons")
        for r in items_df.itertuples():
            cols = st.columns([4, 2, 2])
            with cols[0]:
                st.write(r.item_name)
            with cols[1]:
                st.write(f"Qty: {r.quantity}")
            with cols[2]:
                if st.button("Edit", key=f"edit_{selected_location}_{r.item_name}"):
                    st.session_state["item_input"] = r.item_name
                    st.session_state["qty_input"] = int(r.quantity)

    st.markdown("</div>", unsafe_allow_html=True)

    # --------------------------------------
    # Add / Update Item form
    # --------------------------------------
    st.markdown("<div class='card'><h3>🛠 Add / Update Item</h3>", unsafe_allow_html=True)

    item_name = st.text_input(
        "Item Name",
        value=st.session_state.get("item_input", ""),
        key="item_input_box",
    )

    quantity = st.number_input(
        "Quantity",
        step=1,
        min_value=0,
        value=int(st.session_state.get("qty_input", 0)),
        key="qty_input_box",
    )

    c1, c2 = st.columns([1, 1])

    with c1:
        if st.button("Save / Update", type="primary"):
            if not item_name.strip():
                st.error("Item name cannot be blank.")
            else:
                upsert_inventory(selected_location, item_name, int(quantity))
                st.success(f"Item '{item_name}' saved/updated.")
                st.session_state["item_input"] = item_name
                st.session_state["qty_input"] = int(quantity)
                st.rerun()

    with c2:
        if st.button("Delete Item"):
            if not item_name.strip():
                st.error("Enter an item name to delete.")
            else:
                delete_inventory_item(selected_location, item_name)
                st.warning(f"Item '{item_name}' deleted.")
                st.session_state["item_input"] = ""
                st.session_state["qty_input"] = 0
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ==========================================
# 3. Shortage report (simple)
# ==========================================
st.markdown("## 📉 Shortage Report")

threshold = st.slider("Show items with quantity ≤", min_value=0, max_value=20, value=1)
short_df = get_shortage_report(threshold)

if short_df.empty:
    st.write("No items at or below this threshold.")
else:
    st.dataframe(short_df, use_container_width=True)


# ==========================================
# 4. Admin – Barcode list (read-only)
# ==========================================
st.markdown("## 🧾 Barcode Master (read-only view)")

with engine.begin() as conn:
    barcode_df = pd.read_sql(
        text("SELECT barcode, item_name FROM barcode_master ORDER BY item_name"),
        conn,
    )

st.dataframe(barcode_df, use_container_width=True)
