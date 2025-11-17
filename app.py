import os
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# ======================================================
# 🔗 Database connection
# ======================================================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is not set in Cloud Run")

# Small connection pool – enough for a few concurrent pickers
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=2,
)


# ======================================================
# 🔁 Safe DB helpers – avoid stuck transactions
# ======================================================
def _safe_read_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """
    Run a SELECT and return a DataFrame.
    If any DB error happens, dispose the pool so Cloud Run gets fresh connections.
    """
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {})
    except SQLAlchemyError:
        engine.dispose()
        raise


def _safe_exec(sql: str, params: dict | None = None) -> None:
    """
    Run INSERT / UPDATE / DELETE without returning rows.
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), params or {})
    except SQLAlchemyError:
        engine.dispose()
        raise


# ======================================================
# 📦 Core DB functions
# ======================================================
def get_all_locations() -> list[int]:
    df = _safe_read_df(
        """
        SELECT DISTINCT location_id
        FROM inventory
        ORDER BY location_id
        """
    )
    return df["location_id"].astype(int).tolist()


def get_items_for_location(location_id: int) -> pd.DataFrame:
    return _safe_read_df(
        """
        SELECT item_name, quantity, updated_at, barcode
        FROM inventory
        WHERE location_id = :loc
          AND item_name <> ''
        ORDER BY item_name
        """,
        {"loc": location_id},
    )


def get_current_qty(location_id: int, item_name: str) -> int | None:
    df = _safe_read_df(
        """
        SELECT quantity
        FROM inventory
        WHERE location_id = :loc AND item_name = :item
        LIMIT 1
        """,
        {"loc": location_id, "item": item_name},
    )
    if df.empty:
        return None
    return int(df["quantity"].iloc[0])


def log_movement(location_id: int, item_name: str, delta: int, new_qty: int) -> None:
    if delta == 0:
        return
    _safe_exec(
        """
        INSERT INTO inventory_log (location_id, item_name, quantity_change, new_quantity, changed_at)
        VALUES (:loc, :item, :delta, :new_qty, :ts)
        """,
        {
            "loc": location_id,
            "item": item_name.strip(),
            "delta": int(delta),
            "new_qty": int(new_qty),
            "ts": datetime.utcnow(),
        },
    )


def upsert_item(location_id: int, item_name: str, quantity: int, barcode: str | None):
    """
    Create/update item and log the quantity change.
    """
    item_name = item_name.strip()
    quantity = int(quantity)

    old_qty = get_current_qty(location_id, item_name) or 0
    delta = quantity - old_qty

    _safe_exec(
        """
        INSERT INTO inventory (location_id, item_name, quantity, updated_at, barcode)
        VALUES (:loc, :item, :qty, :ts, :barcode)
        ON CONFLICT (location_id, item_name)
        DO UPDATE SET
            quantity   = EXCLUDED.quantity,
            updated_at = EXCLUDED.updated_at,
            barcode    = COALESCE(EXCLUDED.barcode, inventory.barcode)
        """,
        {
            "loc": location_id,
            "item": item_name,
            "qty": quantity,
            "ts": datetime.utcnow(),
            "barcode": barcode,
        },
    )

    log_movement(location_id, item_name, delta, quantity)


def delete_item(location_id: int, item_name: str):
    """
    Delete an item completely from a location.
    """
    current = get_current_qty(location_id, item_name)
    _safe_exec(
        "DELETE FROM inventory WHERE location_id = :loc AND item_name = :item",
        {"loc": location_id, "item": item_name.strip()},
    )
    if current is not None:
        # Log as full negative movement
        log_movement(location_id, item_name, -current, 0)


def quick_adjust_quantity(location_id: int, item_name: str, delta: int):
    """
    +1 / -1 adjustments from quick buttons, with logging.
    """
    item_name = item_name.strip()
    params = {
        "delta": int(delta),
        "ts": datetime.utcnow(),
        "loc": location_id,
        "item": item_name,
    }

    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE inventory
                    SET quantity   = GREATEST(quantity + :delta, 0),
                        updated_at = :ts
                    WHERE location_id = :loc AND item_name = :item
                    RETURNING quantity
                    """
                ),
                params,
            ).fetchone()
    except SQLAlchemyError:
        engine.dispose()
        raise

    if row is not None:
        new_qty = int(row[0])
        log_movement(location_id, item_name, delta, new_qty)


# ---------- Barcode helpers ----------

def find_item_by_barcode(barcode: str) -> str | None:
    df = _safe_read_df(
        """
        SELECT item_name
        FROM barcode_master
        WHERE barcode = :bc
        LIMIT 1
        """,
        {"bc": barcode},
    )
    if df.empty:
        return None
    return df["item_name"].iloc[0]


def get_locations_for_item(item_name: str) -> pd.DataFrame:
    return _safe_read_df(
        """
        SELECT location_id, quantity, updated_at, barcode
        FROM inventory
        WHERE item_name = :item
        ORDER BY location_id
        """,
        {"item": item_name},
    )


# ======================================================
# 🎨 Streamlit layout & theming
# ======================================================
st.set_page_config(
    page_title="Locofly Inventory System",
    layout="wide",
)

st.markdown(
    """
    <style>
    body {
        background: #F2F4F7;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    .header-box {
        background: linear-gradient(135deg, #4285F4 0%, #6CA0FF 100%);
        padding: 26px 28px;
        color: white;
        border-radius: 18px;
        margin-bottom: 30px;
        box-shadow: 0px 10px 30px rgba(15, 23, 42, 0.35);
    }
    .header-title {
        font-size: 32px;
        font-weight: 800;
        letter-spacing: -0.5px;
        margin-bottom: 4px;
    }
    .header-sub {
        font-size: 14px;
        opacity: 0.92;
    }

    .card {
        background: #ffffff;
        padding: 20px 22px;
        border-radius: 16px;
        box-shadow: 0px 4px 15px rgba(15, 23, 42, 0.08);
        margin-bottom: 18px;
    }

    .qty-chip {
        display:inline-block;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 13px;
        font-weight: 600;
        background:#E8ECFF;
        color:#1D2A73;
    }

    .edit-panel {
        background:#F7F9FB;
        border-radius:14px;
        padding:14px;
        border-left:4px solid #4F8BF9;
        margin-top:8px;
        box-shadow:0px 4px 12px rgba(15, 23, 42, 0.08);
    }

    .stButton>button {
        border-radius: 999px;
        font-weight: 600;
        font-size: 14px;
        padding: 6px 18px;
        border: none;
        box-shadow:0 2px 6px rgba(15,23,42,0.15);
    }

    input, textarea {
        border-radius: 10px !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)

# ======================================================
# 🔝 Header
# ======================================================
st.markdown(
    """
    <div class="header-box">
      <div class="header-title">📦 Locofly Inventory System</div>
      <div class="header-sub">
        Fast, simple, reliable stock control for dark store locations & pickers.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ======================================================
# 📍 Sidebar: Location Manager
# ======================================================
st.sidebar.header("📍 Location Manager")

all_locations = get_all_locations()

# Use session_state so barcode view can "jump" the manager to a location
if "selected_loc_label" not in st.session_state:
    if all_locations:
        st.session_state.selected_loc_label = str(all_locations[0])
    else:
        st.session_state.selected_loc_label = "(Create New)"

location_labels = [str(x) for x in all_locations]
selected_loc_label = st.sidebar.selectbox(
    "Select Location",
    options=["(Create New)"] + location_labels,
    key="selected_loc_label",
)

new_loc_input = st.sidebar.text_input("Enter new location_id (number)")

if st.sidebar.button("Create Location"):
    try:
        new_loc_id = int(new_loc_input)
        if new_loc_id in all_locations:
            st.sidebar.warning("Location already exists.")
        else:
            # Insert empty row so it shows up
            _safe_exec(
                """
                INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                VALUES (:loc, '', 0, :ts)
                ON CONFLICT DO NOTHING
                """,
                {"loc": new_loc_id, "ts": datetime.utcnow()},
            )
            st.sidebar.success(f"Location {new_loc_id} created.")
            st.session_state.selected_loc_label = str(new_loc_id)
            st.rerun()
    except ValueError:
        st.sidebar.error("Location id must be a number.")

active_loc: int | None = None
if selected_loc_label != "(Create New)":
    active_loc = int(selected_loc_label)

# ======================================================
# 🔍 Picker View – barcode first
# ======================================================
with st.container():
    picker_card = st.container()
    with picker_card:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("🔍 Picker View – Scan Product Barcode")

        barcode_input = st.text_input(
            "Scan / Type Product Barcode",
            key="barcode_input",
            placeholder="Example: 8901234567890",
        )
        scan_col, _ = st.columns([1, 4])
        with scan_col:
            scan_pressed = st.button("Search Barcode")

        if scan_pressed and barcode_input.strip():
            bc = barcode_input.strip()
            item_name = find_item_by_barcode(bc)
            if not item_name:
                st.warning("Barcode not found in barcode_master. Add mapping first.")
            else:
                st.success(f"Barcode found → **{item_name}**")
                loc_df = get_locations_for_item(item_name)
                if loc_df.empty:
                    st.info("This item is not stored in any location yet.")
                else:
                    st.markdown("**Stored in these locations:**")
                    st.dataframe(loc_df, use_container_width=True)

                    st.markdown("Tap a location to jump to quick edit:")
                    for _, r in loc_df.iterrows():
                        loc_id = int(r["location_id"])
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.markdown(
                                f"- Location **{loc_id}** · Qty: **{int(r['quantity'])}**"
                            )
                        with c2:
                            if st.button(
                                "Open",
                                key=f"open_loc_{loc_id}_{item_name}",
                            ):
                                st.session_state.selected_loc_label = str(loc_id)
                                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

# If no active location, stop after picker card
if active_loc is None:
    st.info("Select a location on the left to manage its stock.")
    st.stop()

# ======================================================
# 📊 Items table for active location
# ======================================================
items_df = get_items_for_location(active_loc)

st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown(f"### 📊 Current stock – Location `{active_loc}`")
st.dataframe(items_df, use_container_width=True)
st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# ⚡ Quick edit list with +1 / −1 and inline edit
# ======================================================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown("### ⚡ Quick edit")

if items_df.empty:
    st.info("No items in this location yet. Use the form below to add items.")
else:
    for _, row in items_df.iterrows():
        item = row["item_name"]
        qty = int(row["quantity"])

        c1, c2, c3, c4 = st.columns([4, 2, 2, 4])
        with c1:
            st.markdown(f"**{item}**")
        with c2:
            st.markdown(
                f'<span class="qty-chip">Qty: {qty}</span>',
                unsafe_allow_html=True,
            )
        with c3:
            minus = st.button("−1", key=f"minus_{active_loc}_{item}")
            plus = st.button("+1", key=f"plus_{active_loc}_{item}")
        with c4:
            with st.expander("Edit / Delete", expanded=False):
                new_qty = st.number_input(
                    f"Set quantity for {item}",
                    min_value=0,
                    step=1,
                    value=qty,
                    key=f"edit_qty_{active_loc}_{item}",
                )
                save_col, del_col, _ = st.columns([1, 1, 2])
                with save_col:
                    if st.button("Save", key=f"save_{active_loc}_{item}"):
                        upsert_item(active_loc, item, new_qty, barcode=row.get("barcode"))
                        st.success("Updated.")
                        st.rerun()
                with del_col:
                    if st.button("Delete", key=f"del_{active_loc}_{item}"):
                        delete_item(active_loc, item)
                        st.warning("Item deleted.")
                        st.rerun()

        if minus:
            quick_adjust_quantity(active_loc, item, -1)
            st.rerun()

        if plus:
            quick_adjust_quantity(active_loc, item, +1)
            st.rerun()

st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# 🛠 Add / Update item form
# ======================================================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown("### 🛠 Add / Update Item")

col_item, col_qty, col_barcode = st.columns([4, 2, 3])
with col_item:
    form_item_name = st.text_input(
        "Item name",
        key="form_item_name",
        placeholder="e.g. Amul milk 1L",
    )
with col_qty:
    form_qty = st.number_input("Quantity", min_value=0, step=1, key="form_qty")
with col_barcode:
    form_barcode = st.text_input(
        "Barcode (optional)",
        key="form_barcode",
        placeholder="8901…",
    )

save_btn = st.button("Save / Update item", type="primary")

if save_btn:
    if not form_item_name.strip():
        st.error("Item name cannot be blank.")
    else:
        upsert_item(active_loc, form_item_name, form_qty, form_barcode or None)
        st.success(f"Saved '{form_item_name}' at location {active_loc}.")
        st.rerun()

st.markdown("</div>", unsafe_allow_html=True)
