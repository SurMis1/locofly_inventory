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

# Use small pool, you don't need many concurrent connections
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=2,
)


# ======================================================
# 🔁 Safe DB helpers – prevent stuck transactions
# ======================================================
def _safe_read_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """
    Run a SELECT that returns a DataFrame.
    If any DB error happens, dispose the pool so Cloud Run gets fresh connections.
    """
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {})
    except SQLAlchemyError as e:
        # Drop all pooled connections – clears 'transaction is aborted' sessions
        engine.dispose()
        raise e


def _safe_exec(sql: str, params: dict | None = None) -> None:
    """
    Run INSERT / UPDATE / DELETE.
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), params or {})
    except SQLAlchemyError as e:
        engine.dispose()
        raise e


# ======================================================
# 📦 Core queries
# ======================================================
def get_all_locations() -> list[int]:
    df = _safe_read_df(
        """
        SELECT DISTINCT location_id
        FROM inventory
        ORDER BY location_id
        """
    )
    return df["location_id"].tolist()


def get_items_for_location(loc_value) -> pd.DataFrame:
    """
    loc_value may come from selectbox ('1', '2', '(Create New)').
    We only hit DB if it can be parsed as an INT.
    """
    try:
        loc = int(loc_value)
    except (TypeError, ValueError):
        # No valid location selected – return empty table
        return pd.DataFrame(columns=["item_name", "quantity", "updated_at", "barcode"])

    return _safe_read_df(
        """
        SELECT item_name, quantity, updated_at, barcode
        FROM inventory
        WHERE location_id = :loc
          AND item_name <> ''
        ORDER BY item_name
        """,
        {"loc": loc},
    )


def upsert_item(location_id: int, item_name: str, quantity: int, barcode: str | None):
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
            "item": item_name.strip(),
            "qty": int(quantity),
            "ts": datetime.utcnow(),
            "barcode": barcode,
        },
    )

    # Log movement
    _safe_exec(
        """
        INSERT INTO inventory_log (location_id, item_name, quantity_change, new_quantity, changed_at)
        VALUES (:loc, :item, :delta, :new_qty, :ts)
        """,
        {
            "loc": location_id,
            "item": item_name.strip(),
            "delta": quantity,  # simple log for now
            "new_qty": quantity,
            "ts": datetime.utcnow(),
        },
    )


def delete_item(location_id: int, item_name: str):
    _safe_exec(
        "DELETE FROM inventory WHERE location_id = :loc AND item_name = :item",
        {"loc": location_id, "item": item_name.strip()},
    )


def quick_adjust_quantity(location_id: int, item_name: str, delta: int):
    """
    +1 / -1 adjustments from the quick buttons.
    """
    _safe_exec(
        """
        UPDATE inventory
        SET quantity   = GREATEST(quantity + :delta, 0),
            updated_at = :ts
        WHERE location_id = :loc
          AND item_name   = :item
        """,
        {
            "delta": int(delta),
            "ts": datetime.utcnow(),
            "loc": location_id,
            "item": item_name.strip(),
        },
    )


# ======================================================
# 🎨 Streamlit layout
# ======================================================
st.set_page_config(
    page_title="Locofly Inventory System",
    layout="wide",
)

st.markdown(
    """
    <style>
    body { background-color: #F6F7FB; }

    .header-box {
        background: linear-gradient(90deg, #4F8BF9, #6CA2F8);
        padding: 22px 28px;
        color: white;
        border-radius: 16px;
        margin-bottom: 26px;
        box-shadow: 0px 8px 24px rgba(0,0,0,0.08);
    }
    .header-title {
        font-size: 30px;
        font-weight: 700;
        margin-bottom: 4px;
    }
    .header-sub {
        font-size: 15px;
        opacity: 0.95;
    }

    .card {
        background: #FFFFFF;
        border-radius: 14px;
        padding: 20px 22px;
        box-shadow: 0 4px 15px rgba(15, 23, 42, 0.08);
        margin-bottom: 20px;
    }

    .qty-chip {
        display:inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        background:#EEF2FF;
        color:#3730A3;
    }

    .edit-panel {
        background:#F9FAFB;
        border-radius:12px;
        padding:12px 14px;
        margin-top:6px;
        border:1px dashed #E5E7EB;
    }

    .stButton>button {
        border-radius: 999px;
        font-weight: 600;
        padding: 4px 16px;
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
      <div class="header-sub">Fast, simple stock control for dark store locations.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ======================================================
# 📍 Sidebar: Location Manager
# ======================================================
st.sidebar.header("📍 Location Manager")

all_locations = get_all_locations()

# Show locations as strings but remember int later
location_labels = [str(x) for x in all_locations]
selected_loc_label = st.sidebar.selectbox(
    "Select Location",
    options=["(Create New)"] + location_labels,
)

new_loc_input = st.sidebar.text_input("Enter new location_id (number)")

if st.sidebar.button("Create Location"):
    try:
        new_loc_id = int(new_loc_input)
        if new_loc_id in all_locations:
            st.sidebar.warning("Location already exists.")
        else:
            # Put a dummy empty row so location appears
            _safe_exec(
                """
                INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                VALUES (:loc, '', 0, :ts)
                ON CONFLICT DO NOTHING
                """,
                {"loc": new_loc_id, "ts": datetime.utcnow()},
            )
            st.sidebar.success(f"Location {new_loc_id} created.")
            st.experimental_rerun()
    except ValueError:
        st.sidebar.error("Location id must be a number.")

# Determine active location id
active_loc: int | None = None
if selected_loc_label != "(Create New)":
    active_loc = int(selected_loc_label)

# ======================================================
# 🔍 Picker barcode section (top)
# ======================================================
st.subheader("🔍 Picker View – Scan Product Barcode")

barcode_input = st.text_input("Scan / Type Product Barcode", key="barcode_input")
col_scan_btn, _ = st.columns([1, 4])
with col_scan_btn:
    scan_pressed = st.button("Search Barcode")

if scan_pressed and barcode_input.strip():
    df_barc = _safe_read_df(
        """
        SELECT item_name, barcode
        FROM inventory
        WHERE barcode = :bc
        LIMIT 10
        """,
        {"bc": barcode_input.strip()},
    )
    if df_barc.empty:
        st.warning("Barcode not linked to any item yet.")
    else:
        st.info(
            "Barcode matches: "
            + ", ".join(df_barc["item_name"].astype(str).tolist())
        )

# ======================================================
# 📊 Items table for selected location
# ======================================================
if active_loc is None:
    st.info("Select a location on the left, or create a new one.")
    st.stop()

items_df = get_items_for_location(active_loc)

st.markdown("### 📊 Current stock")
st.dataframe(items_df, use_container_width=True)

# ======================================================
# ⚡ Quick edit list with +1 / -1 and inline edit
# ======================================================
st.markdown("### ⚡ Quick edit buttons")

if items_df.empty:
    st.info("No items in this location yet.")
else:
    for _, row in items_df.iterrows():
        item = row["item_name"]
        qty = int(row["quantity"])

        c1, c2, c3, c4 = st.columns([4, 2, 3, 3])
        with c1:
            st.markdown(f"**{item}**")
        with c2:
            st.markdown(f'<span class="qty-chip">Qty: {qty}</span>', unsafe_allow_html=True)

        with c3:
            minus = st.button("−1", key=f"minus_{active_loc}_{item}")
            plus = st.button("+1", key=f"plus_{active_loc}_{item}")
        with c4:
            show_edit = st.button("Edit", key=f"edit_{active_loc}_{item}")

        if minus:
            quick_adjust_quantity(active_loc, item, -1)
            st.experimental_rerun()
        if plus:
            quick_adjust_quantity(active_loc, item, +1)
            st.experimental_rerun()

        if show_edit:
            # Inline slide-down panel
            with st.container():
                st.markdown('<div class="edit-panel">', unsafe_allow_html=True)
                new_qty = st.number_input(
                    f"Set quantity for **{item}**",
                    min_value=0,
                    step=1,
                    value=qty,
                    key=f"edit_qty_{active_loc}_{item}",
                )
                col_save, col_del, _ = st.columns([1, 1, 4])
                with col_save:
                    if st.button("Save", key=f"save_{active_loc}_{item}"):
                        upsert_item(active_loc, item, new_qty, barcode=None)
                        st.experimental_rerun()
                with col_del:
                    if st.button("Delete", key=f"del_{active_loc}_{item}"):
                        delete_item(active_loc, item)
                        st.experimental_rerun()
                st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# 🛠 Add / Update item (bottom form)
# ======================================================
st.markdown("### 🛠 Add / Update Item")

col_item, col_qty, col_barcode = st.columns([4, 2, 3])
with col_item:
    form_item_name = st.text_input("Item name", key="form_item_name")
with col_qty:
    form_qty = st.number_input("Quantity", min_value=0, step=1, key="form_qty")
with col_barcode:
    form_barcode = st.text_input("Barcode (optional)", key="form_barcode")

save_btn = st.button("Save / Update item", type="primary")

if save_btn:
    if not form_item_name.strip():
        st.error("Item name cannot be blank.")
    else:
        upsert_item(active_loc, form_item_name, form_qty, form_barcode or None)
        st.success(f"Saved '{form_item_name}' at location {active_loc}.")
        st.experimental_rerun()
