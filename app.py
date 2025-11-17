import os
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# ======================================================
# 🔗 PostgreSQL connection
# ======================================================

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    st.stop()  # fail fast if env var not present

engine = create_engine(DATABASE_URL)

# ======================================================
# ⚙️ Small helpers
# ======================================================

def get_all_locations():
    """Return sorted list of existing location_ids."""
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT location_id FROM inventory ORDER BY location_id")
        ).fetchall()
    return [r[0] for r in rows]


def get_items_for_location(loc_id: int) -> pd.DataFrame:
    """Fetch items for a given location."""
    with engine.begin() as conn:
        # try to include barcode if column exists; fallback if not
        try:
            df = pd.read_sql(
                text(
                    """
                    SELECT item_name, quantity, updated_at, barcode
                    FROM inventory
                    WHERE location_id = :loc AND item_name <> ''
                    ORDER BY item_name
                    """
                ),
                conn,
                params={"loc": loc_id},
            )
        except Exception:
            df = pd.read_sql(
                text(
                    """
                    SELECT item_name, quantity, updated_at
                    FROM inventory
                    WHERE location_id = :loc AND item_name <> ''
                    ORDER BY item_name
                    """
                ),
                conn,
                params={"loc": loc_id},
            )
    return df


def upsert_item(loc_id: int, item_name: str, new_qty: int, source: str, note: str = ""):
    """Upsert into inventory and log into inventory_log."""
    item_name = item_name.strip()
    now = datetime.now()

    with engine.begin() as conn:
        # Get previous quantity (if any)
        row = conn.execute(
            text(
                """
                SELECT quantity
                FROM inventory
                WHERE location_id = :loc AND item_name = :item
                """
            ),
            {"loc": loc_id, "item": item_name},
        ).fetchone()

        old_qty = row[0] if row else 0
        change = new_qty - old_qty

        # Upsert into inventory
        conn.execute(
            text(
                """
                INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                VALUES (:loc, :item, :qty, :ts)
                ON CONFLICT (location_id, item_name)
                DO UPDATE SET quantity = :qty, updated_at = :ts
                """
            ),
            {"loc": loc_id, "item": item_name, "qty": new_qty, "ts": now},
        )

        # Log the change
        conn.execute(
            text(
                """
                INSERT INTO inventory_log
                    (location_id, item_name, old_quantity, new_quantity, change, source, note, changed_at)
                VALUES (:loc, :item, :old_q, :new_q, :chg, :src, :note, :ts)
                """
            ),
            {
                "loc": loc_id,
                "item": item_name,
                "old_q": old_qty,
                "new_q": new_qty,
                "chg": change,
                "src": source,
                "note": note,
                "ts": now,
            },
        )


def delete_item(loc_id: int, item_name: str, source: str = "delete_button"):
    item_name = item_name.strip()
    now = datetime.now()

    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT quantity
                FROM inventory
                WHERE location_id = :loc AND item_name = :item
                """
            ),
            {"loc": loc_id, "item": item_name},
        ).fetchone()

        old_qty = row[0] if row else 0

        conn.execute(
            text(
                "DELETE FROM inventory WHERE location_id = :loc AND item_name = :item"
            ),
            {"loc": loc_id, "item": item_name},
        )

        conn.execute(
            text(
                """
                INSERT INTO inventory_log
                    (location_id, item_name, old_quantity, new_quantity, change, source, note, changed_at)
                VALUES (:loc, :item, :old_q, 0, :chg, :src, :note, :ts)
                """
            ),
            {
                "loc": loc_id,
                "item": item_name,
                "old_q": old_qty,
                "chg": -old_qty,
                "src": source,
                "note": "delete",
                "ts": now,
            },
        )


def create_location(loc_id: int):
    """Create a blank location (one dummy row so it appears)."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO inventory (location_id, item_name, quantity, updated_at)
                VALUES (:loc, '', 0, :ts)
                ON CONFLICT (location_id, item_name) DO NOTHING
                """
            ),
            {"loc": loc_id, "ts": datetime.now()},
        )


def lookup_item_by_barcode(barcode: str):
    """Return item_name for a barcode, or None."""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT item_name FROM barcode_master WHERE barcode = :b"),
            {"b": barcode},
        ).fetchone()
    return row[0] if row else None


def get_locations_for_item(item_name: str) -> pd.DataFrame:
    with engine.begin() as conn:
        df = pd.read_sql(
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
    return df


# ======================================================
# 🎨 Page layout / styling
# ======================================================

st.set_page_config(page_title="Locofly Inventory System", layout="wide")

st.markdown(
    """
<style>
body { background-color: #F6F8FC; }

/* Header card */
.header-box {
    background: linear-gradient(90deg, #4F8BF9, #6CA2F8);
    padding: 18px 24px;
    color: white;
    border-radius: 12px;
    margin-bottom: 20px;
}

/* Generic card */
.card {
    background: white;
    padding: 20px;
    border-radius: 16px;
    box-shadow: 0px 2px 6px rgba(15, 23, 42, 0.12);
    margin-bottom: 18px;
}

/* Quantity pill */
.qty-pill {
    display:inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 600;
    color: #111827;
}
.qty-ok    { background:#DCFCE7; }
.qty-low   { background:#FEF9C3; }
.qty-high  { background:#FEE2E2; }

/* Bottom sheet overlay + panel */
.inventory-overlay {
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.35);
    z-index: 998;
}
.inventory-sheet {
    position: fixed;
    left: 0; right: 0; bottom: 0;
    background: #FFFFFF;
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -6px 20px rgba(15, 23, 42, 0.25);
    padding: 18px 20px 24px 20px;
    z-index: 999;
    animation: slideUpInventory 0.22s ease-out;
}
@keyframes slideUpInventory {
    from { transform: translateY(100%); opacity: 0; }
    to   { transform: translateY(0);   opacity: 1; }
}

/* Make buttons a bit nicer */
.stButton>button {
    border-radius: 999px;
    font-weight: 600;
    padding: 4px 14px;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="header-box">
  <h2 style="margin:0;">📦 Locofly Inventory System</h2>
  <p style="margin-top:4px;margin-bottom:0;font-size:14px;opacity:0.95;">
    Fast, simple stock control for dark store locations.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

# ======================================================
# 🧠 Session-state for bottom sheet
# ======================================================

if "edit_open" not in st.session_state:
    st.session_state.edit_open = False
if "edit_loc" not in st.session_state:
    st.session_state.edit_loc = None
if "edit_item" not in st.session_state:
    st.session_state.edit_item = ""
if "edit_current_qty" not in st.session_state:
    st.session_state.edit_current_qty = 0
if "edit_target_qty" not in st.session_state:
    st.session_state.edit_target_qty = 0

# ======================================================
# 🔀 Mode detection (admin vs picker)
# ======================================================

params = st.query_params

mode = params.get("mode", "admin")
if isinstance(mode, list):
    mode = mode[0]
mode = (mode or "admin").lower()

is_picker_mode = mode == "picker"

qr_loc = params.get("loc")
if isinstance(qr_loc, list):
    qr_loc = qr_loc[0]
qr_item = params.get("item")
if isinstance(qr_item, list):
    qr_item = qr_item[0]

# ======================================================
# 📍 Sidebar (admin only)
# ======================================================

locations = get_all_locations()

selected_loc = None  # actual int or None

if not is_picker_mode:
    st.sidebar.header("📍 Location Manager")

    loc_options = ["(Create New)"] + [str(l) for l in locations]
    choice = st.sidebar.selectbox("Select Location", loc_options, index=0)

    new_loc_input = st.sidebar.text_input("Enter new location_id (number)")

    if st.sidebar.button("Create Location"):
        if not new_loc_input.strip():
            st.sidebar.error("Location ID cannot be blank.")
        else:
            try:
                loc_int = int(new_loc_input)
                create_location(loc_int)
                st.sidebar.success(f"Location {loc_int} created.")
                st.rerun()
            except ValueError:
                st.sidebar.error("Location ID must be a number.")

    if choice != "(Create New)":
        try:
            selected_loc = int(choice)
        except ValueError:
            selected_loc = None
else:
    # Picker mode: take loc from query param if present
    if qr_loc is not None:
        try:
            selected_loc = int(qr_loc)
        except ValueError:
            selected_loc = None

# ======================================================
# 🔍 Barcode Scan Area (top, visible in both modes)
# ======================================================

with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 🔍 Picker View – Scan Product Barcode")

    col_scan1, col_scan2 = st.columns([3, 1])
    with col_scan1:
        barcode_input = st.text_input("Scan / Type Product Barcode", value="")

    with col_scan2:
        search_pressed = st.button("Search Barcode", key="search_barcode_btn")

    if search_pressed:
        b = barcode_input.strip()
        if not b:
            st.error("Please scan or type a valid barcode.")
        else:
            name = lookup_item_by_barcode(b)
            if not name:
                st.error("Barcode not found in barcode_master.")
            else:
                st.success(f"Product found: **{name}**")

                loc_df = get_locations_for_item(name)
                if loc_df.empty:
                    st.warning("This product is not stored in any location yet.")
                else:
                    st.markdown("#### 📍 Stored in these locations")
                    st.dataframe(loc_df, use_container_width=True)
                    st.markdown("##### 👉 Tap to open location")

                    for row in loc_df.itertuples():
                        L = row.location_id
                        st.markdown(
                            f"- 🔗 [Open Location {L}](?mode=picker&loc={L}&item={name})"
                        )

    st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# 📍 Determine active location to show
# ======================================================

# If no location selected yet, but query provided one, use it
if selected_loc is None and qr_loc is not None:
    try:
        selected_loc = int(qr_loc)
    except ValueError:
        selected_loc = None

if selected_loc is None:
    # nothing to show yet
    st.info("Select a location from the sidebar or open via QR/link.")
    st.stop()

# ======================================================
# 🧾 Items table for active location
# ======================================================

items_df = get_items_for_location(selected_loc)

with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f"### 📍 Location: `{selected_loc}`")

    if items_df.empty:
        st.write("No items at this location yet.")
    else:
        st.dataframe(items_df, use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# ⚡ Quick Edit list (per-item buttons)
# ======================================================

with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### ⚡ Quick edit")

    if items_df.empty:
        st.caption("No items to quick-edit yet.")
    else:
        for row in items_df.itertuples():
            item = row.item_name
            qty = int(row.quantity)

            # Quantity pill color
            if qty <= 3:
                cls = "qty-low"
            elif qty >= 50:
                cls = "qty-high"
            else:
                cls = "qty-ok"

            qty_html = f'<span class="qty-pill {cls}">Qty: {qty}</span>'

            c1, c2, c3, c4 = st.columns([6, 2, 2, 2])
            with c1:
                st.markdown(f"**{item}**<br/>{qty_html}", unsafe_allow_html=True)

            def open_editor(target_qty: int, source: str):
                st.session_state.edit_open = True
                st.session_state.edit_loc = selected_loc
                st.session_state.edit_item = item
                st.session_state.edit_current_qty = qty
                st.session_state.edit_target_qty = max(target_qty, 0)
                st.session_state.edit_source = source
                st.session_state.edit_note = ""
                st.rerun()

            with c2:
                if st.button("+1", key=f"plus_{selected_loc}_{item}"):
                    open_editor(qty + 1, source="plus_one")

            with c3:
                if st.button("-1", key=f"minus_{selected_loc}_{item}"):
                    open_editor(qty - 1, source="minus_one")

            with c4:
                if st.button("Edit", key=f"edit_{selected_loc}_{item}"):
                    open_editor(qty, source="edit_button")

    st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# 🛠 Add / Update / Delete (manual form)
# ======================================================

with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 🛠 Add / Update Item")

    default_item_name = qr_item if qr_item else ""
    item_name_input = st.text_input("Item Name", value=default_item_name, key="manual_item")
    qty_input = st.number_input("Quantity", step=1, min_value=0, key="manual_qty")

    col_manual1, col_manual2, col_manual3 = st.columns([2, 2, 2])
    with col_manual1:
        if st.button("Save / Update", type="primary", key="manual_save_btn"):
            if not item_name_input.strip():
                st.error("Item name cannot be blank.")
            else:
                upsert_item(
                    selected_loc,
                    item_name_input,
                    int(qty_input),
                    source="manual_form",
                    note="manual update",
                )
                st.success(f"Item '{item_name_input}' saved.")
                st.rerun()

    with col_manual2:
        if st.button("Delete Item", key="manual_delete_btn"):
            if not item_name_input.strip():
                st.error("Enter item name to delete.")
            else:
                delete_item(selected_loc, item_name_input)
                st.warning(f"Item '{item_name_input}' deleted.")
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ======================================================
# 🪟 Bottom Sheet Editor (slide-style)
# ======================================================

if st.session_state.edit_open and st.session_state.edit_item:
    # Overlay
    st.markdown(
        """
        <div class="inventory-overlay"></div>
        """,
        unsafe_allow_html=True,
    )

    # "Fixed" bottom panel (looks like slider)
    st.markdown(
        """
        <div class="inventory-sheet">
          <h4 style="margin-top:0;margin-bottom:4px;">✏️ Edit Quantity</h4>
          <p style="margin:0;font-size:14px;color:#6B7280;">
            {item_label}
          </p>
        </div>
        """.format(
            item_label=f"Location {st.session_state.edit_loc} · {st.session_state.edit_item}"
        ),
        unsafe_allow_html=True,
    )

    # The HTML panel above is visual. Widgets go just below, but visually aligned.
    with st.container():
        st.write("")  # small spacer

        col_a, col_b = st.columns([2, 1])
        with col_a:
            st.markdown(
                f"**Current quantity:** {st.session_state.edit_current_qty}"
            )
            new_qty = st.number_input(
                "New quantity",
                min_value=0,
                step=1,
                key="sheet_new_qty",
                value=st.session_state.edit_target_qty,
            )
        with col_b:
            st.markdown("**Adjust**")
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("+1", key="sheet_plus1"):
                    st.session_state.edit_target_qty = (
                        st.session_state.edit_target_qty + 1
                    )
                    st.rerun()
            with col_btn2:
                if st.button("-1", key="sheet_minus1"):
                    st.session_state.edit_target_qty = max(
                        st.session_state.edit_target_qty - 1, 0
                    )
                    st.rerun()

        st.markdown("**Quick presets**")
        preset_cols = st.columns(4)
        for preset, pc in zip([5, 10, 15, 20], preset_cols):
            with pc:
                if st.button(str(preset), key=f"preset_{preset}"):
                    st.session_state.edit_target_qty = preset
                    st.rerun()

        note = st.text_input(
            "Note (optional)", value=st.session_state.get("edit_note", ""), key="sheet_note"
        )

        col_save, col_cancel = st.columns(2)
        with col_save:
            if st.button("💾 Save changes", type="primary", key="sheet_save"):
                upsert_item(
                    st.session_state.edit_loc,
                    st.session_state.edit_item,
                    int(new_qty),
                    source=st.session_state.get("edit_source", "quick_edit"),
                    note=note,
                )
                st.session_state.edit_open = False
                st.success("Quantity updated.")
                st.rerun()

        with col_cancel:
            if st.button("Cancel", key="sheet_cancel"):
                st.session_state.edit_open = False
                st.rerun()
