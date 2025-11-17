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

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=2,
)

# ======================================================
# 🔁 Safe DB helpers (avoid stuck transactions)
# ======================================================
def _safe_read_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {})
    except SQLAlchemyError as e:
        engine.dispose()
        raise e


def _safe_exec(sql: str, params: dict | None = None) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), params or {})
    except SQLAlchemyError as e:
        engine.dispose()
        raise e

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


def get_items_for_location(loc_value) -> pd.DataFrame:
    try:
        loc = int(loc_value)
    except (TypeError, ValueError):
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


def log_movement(location_id: int, item_name: str, delta: int, new_qty: int, action: str):
    """
    Write a row to inventory_log.
    Schema expected:
      id SERIAL PK,
      location_id INT NOT NULL,
      item_name TEXT NOT NULL,
      quantity_change INT,
      new_quantity INT,
      changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      action TEXT NOT NULL
    """
    _safe_exec(
        """
        INSERT INTO inventory_log (
            location_id,
            item_name,
            quantity_change,
            new_quantity,
            changed_at,
            action
        )
        VALUES (:loc, :item, :delta, :new_qty, :ts, :action)
        """,
        {
            "loc": location_id,
            "item": item_name.strip(),
            "delta": int(delta),
            "new_qty": int(new_qty),
            "ts": datetime.utcnow(),
            "action": action,
        },
    )


def upsert_item(location_id: int, item_name: str, quantity: int, barcode: str | None):
    item = item_name.strip()
    qty = int(quantity)

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
            "item": item,
            "qty": qty,
            "ts": datetime.utcnow(),
            "barcode": barcode,
        },
    )

    log_movement(location_id, item, delta=qty, new_qty=qty, action="upsert")


def delete_item(location_id: int, item_name: str):
    item = item_name.strip()
    _safe_exec(
        "DELETE FROM inventory WHERE location_id = :loc AND item_name = :item",
        {"loc": location_id, "item": item},
    )
    log_movement(location_id, item, delta=0, new_qty=0, action="delete")


def quick_adjust_quantity(location_id: int, item_name: str, delta: int):
    """
    +1 / -1 adjustments from quick buttons.
    """
    item = item_name.strip()

    # Get current quantity
    df = _safe_read_df(
        """
        SELECT quantity
        FROM inventory
        WHERE location_id = :loc
          AND item_name   = :item
        """,
        {"loc": location_id, "item": item},
    )
    if df.empty:
        return

    current_qty = int(df.iloc[0]["quantity"])
    new_qty = max(current_qty + int(delta), 0)

    _safe_exec(
        """
        UPDATE inventory
        SET quantity   = :new_qty,
            updated_at = :ts
        WHERE location_id = :loc
          AND item_name   = :item
        """,
        {
            "new_qty": new_qty,
            "ts": datetime.utcnow(),
            "loc": location_id,
            "item": item,
        },
    )

    log_movement(location_id, item, delta=int(delta), new_qty=new_qty, action="quick-adjust")

# ======================================================
# 🎨 Streamlit global config
# ======================================================
st.set_page_config(
    page_title="Locofly Inventory System",
    layout="wide",
)

# Mobile-first CSS
st.markdown(
    """
    <style>
    /* Make content full width but keep a nice max width on desktop */
    .block-container {
        padding-top: 0.6rem;
        padding-bottom: 3rem;
        padding-left: 0.9rem;
        padding-right: 0.9rem;
        max-width: 900px;
        margin: 0 auto;
    }

    body {
        background-color: #F5F7FB;
        font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    }

    .lf-header-card {
        background: linear-gradient(135deg, #2563EB, #4F46E5);
        padding: 16px 18px;
        border-radius: 18px;
        color: white;
        box-shadow: 0 14px 30px rgba(37, 99, 235, 0.25);
        margin-bottom: 14px;
    }
    .lf-header-title {
        font-size: 24px;
        font-weight: 700;
        margin-bottom: 4px;
        display:flex;
        align-items:center;
        gap:0.4rem;
    }
    .lf-header-sub {
        font-size: 13px;
        opacity: 0.9;
    }

    .lf-chip-loc {
        display:inline-flex;
        align-items:center;
        gap:0.25rem;
        background: rgba(15,23,42,0.25);
        padding: 4px 9px;
        border-radius: 999px;
        font-size: 11px;
        margin-top: 4px;
    }

    .lf-card {
        background: #FFFFFF;
        border-radius: 14px;
        padding: 14px 14px 10px 14px;
        box-shadow: 0 4px 18px rgba(15,23,42,0.08);
        margin-bottom: 12px;
    }

    .lf-card-title {
        font-size: 16px;
        font-weight: 600;
        margin-bottom: 4px;
        display:flex;
        align-items:center;
        gap:0.45rem;
    }

    .lf-subtext {
        font-size: 12px;
        color:#6B7280;
        margin-bottom: 6px;
    }

    .lf-item-card {
        border-radius: 12px;
        padding: 10px 12px;
        background: #F9FAFB;
        border: 1px solid #E5E7EB;
        margin-bottom: 8px;
    }

    .lf-item-header {
        display:flex;
        justify-content:space-between;
        align-items:center;
        gap:0.75rem;
    }

    .lf-item-name {
        font-weight: 600;
        font-size: 14px;
        color:#111827;
    }

    .lf-qty-chip {
        display:inline-flex;
        align-items:center;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        background:#EEF2FF;
        color:#3730A3;
        border: 1px solid #E0E7FF;
    }

    .lf-item-actions {
        margin-top: 8px;
    }

    .lf-item-actions-row {
        display:flex;
        gap:0.4rem;
        align-items:center;
    }

    .lf-small-note {
        font-size:11px;
        color:#9CA3AF;
    }

    .stButton>button {
        border-radius: 999px;
        font-weight: 600;
        padding: 4px 14px;
        font-size: 13px;
    }

    /* Primary pill buttons */
    .lf-pill-primary button {
        background: linear-gradient(135deg,#2563EB,#4F46E5);
        color:white;
        border:none;
    }

    .lf-pill-ghost button {
        background: white;
        border:1px solid #E5E7EB;
        color:#374151;
    }

    .lf-plusminus button {
        width: 44px;
        height: 32px;
        border-radius: 999px;
        font-size: 16px;
        font-weight: 700;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.6rem;
            padding-right: 0.6rem;
        }
        .lf-item-actions-row {
            gap:0.3rem;
        }
        .stDataFrame {
            font-size: 11px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ======================================================
# 🔍 Query params: allow ?loc=...&item=...
# ======================================================
qr_params = st.query_params if hasattr(st, "query_params") else {}
qr_loc = qr_params.get("loc")
qr_item = qr_params.get("item")

# ======================================================
# 🧭 Top header + location selector (mobile-style)
# ======================================================
all_locations = get_all_locations()

# Fallback if no locations yet
if not all_locations:
    st.markdown(
        """
        <div class="lf-header-card">
            <div class="lf-header-title">📦 Locofly Inventory System</div>
            <div class="lf-header-sub">
                No locations yet. Create your first location below to start tracking stock.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    active_loc_initial = None
    # Use QR loc if valid
    if qr_loc:
        try:
            loc_int = int(qr_loc)
            if loc_int in all_locations:
                active_loc_initial = str(loc_int)
        except ValueError:
            pass
    if active_loc_initial is None:
        active_loc_initial = str(all_locations[0])

    st.markdown(
        f"""
        <div class="lf-header-card">
            <div class="lf-header-title">
                📦 Locofly Inventory System
            </div>
            <div class="lf-header-sub">
                Fast, simple stock control for dark store locations.
                <div class="lf-chip-loc">
                    <span>Active location:</span>
                    <strong>{active_loc_initial}</strong>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Location manager card
with st.container():
    st.markdown('<div class="lf-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="lf-card-title">📍 Location manager</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="lf-subtext">Choose a location or create a new rack / bin for the store.</div>',
        unsafe_allow_html=True,
    )

    col_loc_sel, col_new_loc = st.columns([2, 2])

    # Select existing
    with col_loc_sel:
        loc_options = [str(l) for l in all_locations] if all_locations else []
        selected_loc_label = st.selectbox(
            "Active location",
            options=loc_options,
            index=loc_options.index(active_loc_initial) if all_locations else 0,
            key="active_loc_select",
        )

    # Create new
    with col_new_loc:
        new_loc_input = st.text_input("New location id (number)", key="new_loc_input")
        create_new = st.button("Create location", key="btn_create_loc")

        if create_new:
            try:
                new_loc_id = int(new_loc_input)
                if new_loc_id in all_locations:
                    st.warning("Location already exists.")
                else:
                    _safe_exec(
                        """
                        INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                        VALUES (:loc, '', 0, :ts)
                        ON CONFLICT DO NOTHING
                        """,
                        {"loc": new_loc_id, "ts": datetime.utcnow()},
                    )
                    st.success(f"Location {new_loc_id} created.")
                    st.rerun()
            except ValueError:
                st.error("Location id must be a number.")

    st.markdown("</div>", unsafe_allow_html=True)

# Determine current active loc
try:
    active_loc = int(selected_loc_label)
except (TypeError, ValueError):
    st.stop()

# ======================================================
# 🔍 Picker – Barcode scan card
# ======================================================
with st.container():
    st.markdown('<div class="lf-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="lf-card-title">🔍 Picker view – scan barcode</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="lf-subtext">Focus the input, scan with phone camera / scanner, and hit search.</div>',
        unsafe_allow_html=True,
    )

    col_bc, col_btn = st.columns([3, 1])
    with col_bc:
        barcode_input = st.text_input(
            "Scan or type product barcode",
            key="barcode_input",
            value=str(qr_item) if qr_item else "",
        )
    with col_btn:
        st.markdown('<div class="lf-pill-primary">', unsafe_allow_html=True)
        scan_pressed = st.button("Search barcode", key="btn_search_barcode")
        st.markdown("</div>", unsafe_allow_html=True)

    if scan_pressed and barcode_input.strip():
        df_barc = _safe_read_df(
            """
            SELECT item_name, location_id
            FROM inventory
            WHERE barcode = :bc
              AND item_name <> ''
            ORDER BY location_id, item_name
            """,
            {"bc": barcode_input.strip()},
        )
        if df_barc.empty:
            st.warning("Barcode not linked to any item yet.")
        else:
            st.success("Barcode found:")
            st.dataframe(df_barc, use_container_width=True, hide_index=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# 📊 Current stock table
# ======================================================
items_df = get_items_for_location(active_loc)

with st.container():
    st.markdown('<div class="lf-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="lf-card-title">📊 Current stock</div>',
        unsafe_allow_html=True,
    )

    if items_df.empty:
        st.info("No items in this location yet. Add items below.")
    else:
        st.dataframe(items_df, use_container_width=True, hide_index=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# ⚡ Quick edit section (mobile cards)
# ======================================================
with st.container():
    st.markdown('<div class="lf-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="lf-card-title">⚡ Quick edit</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="lf-subtext">Tap +1 / –1 to adjust stock, or use edit for precise quantity & delete.</div>',
        unsafe_allow_html=True,
    )

    if items_df.empty:
        st.info("No items to quick-edit here.")
    else:
        for _, row in items_df.iterrows():
            item = str(row["item_name"])
            qty = int(row["quantity"])
            barcode_val = row.get("barcode", None)

            # Wrapper card
            st.markdown('<div class="lf-item-card">', unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="lf-item-header">
                    <div class="lf-item-name">{item}</div>
                    <div class="lf-qty-chip">Qty: {qty}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if barcode_val:
                st.markdown(
                    f'<div class="lf-small-note">Barcode: {barcode_val}</div>',
                    unsafe_allow_html=True,
                )

            # Action row
            st.markdown('<div class="lf-item-actions">', unsafe_allow_html=True)
            c_minus, c_plus, c_edit = st.columns([1, 1, 2.2])

            with c_minus:
                st.markdown('<div class="lf-plusminus">', unsafe_allow_html=True)
                minus = st.button("−", key=f"minus_{active_loc}_{item}")
                st.markdown("</div>", unsafe_allow_html=True)

            with c_plus:
                st.markdown('<div class="lf-plusminus">', unsafe_allow_html=True)
                plus = st.button("+", key=f"plus_{active_loc}_{item}")
                st.markdown("</div>", unsafe_allow_html=True)

            with c_edit:
                edit_mode = st.selectbox(
                    "Edit / Delete",
                    options=["Choose", "Edit quantity", "Delete item"],
                    key=f"mode_{active_loc}_{item}",
                    label_visibility="collapsed",
                )

            if minus:
                quick_adjust_quantity(active_loc, item, -1)
                st.rerun()
            if plus:
                quick_adjust_quantity(active_loc, item, +1)
                st.rerun()

            # Slide-down panel for edit / delete
            if edit_mode == "Edit quantity":
                new_qty = st.number_input(
                    f"Set quantity for {item}",
                    min_value=0,
                    step=1,
                    value=qty,
                    key=f"qty_edit_{active_loc}_{item}",
                )
                col_save, _ = st.columns([1, 3])
                with col_save:
                    st.markdown('<div class="lf-pill-primary">', unsafe_allow_html=True)
                    save_btn = st.button("Save", key=f"save_{active_loc}_{item}")
                    st.markdown("</div>", unsafe_allow_html=True)
                if save_btn:
                    upsert_item(active_loc, item, new_qty, barcode_val)
                    st.rerun()

            elif edit_mode == "Delete item":
                col_del, _ = st.columns([1, 3])
                with col_del:
                    st.markdown('<div class="lf-pill-ghost">', unsafe_allow_html=True)
                    del_btn = st.button("Confirm delete", key=f"del_{active_loc}_{item}")
                    st.markdown("</div>", unsafe_allow_html=True)
                if del_btn:
                    delete_item(active_loc, item)
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)  # lf-item-actions
            st.markdown("</div>", unsafe_allow_html=True)  # lf-item-card

    st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# 🛠 Add / Update item form
# ======================================================
with st.container():
    st.markdown('<div class="lf-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="lf-card-title">🛠 Add / Update item</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="lf-subtext">Use this when you are stocking a new product or doing a full correction.</div>',
        unsafe_allow_html=True,
    )

    col_item, col_qty, col_barcode = st.columns([2.6, 1.2, 2])
    with col_item:
        form_item_name = st.text_input("Item name", key="form_item_name")
    with col_qty:
        form_qty = st.number_input("Quantity", min_value=0, step=1, key="form_qty")
    with col_barcode:
        form_barcode = st.text_input("Barcode (optional)", key="form_barcode")

    st.markdown('<div class="lf-pill-primary">', unsafe_allow_html=True)
    save_btn_main = st.button("Save / update item", key="btn_save_item")
    st.markdown("</div>", unsafe_allow_html=True)

    if save_btn_main:
        if not form_item_name.strip():
            st.error("Item name cannot be blank.")
        else:
            upsert_item(active_loc, form_item_name, form_qty, form_barcode or None)
            st.success(f"Saved '{form_item_name}' at location {active_loc}.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
