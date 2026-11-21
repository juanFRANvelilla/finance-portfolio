import io
import logging
import re
from decimal import Decimal
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.monthly_category_expense import MonthlyCategoryExpense, MonthlyCategoryExpenseItem
from app.schemas.expense import CategoryExpenseItem, ExpenseItemDetail, MonthlyExpensesResponse

logger = logging.getLogger(__name__)

CATEGORY_RULES: list[tuple[str, str, str, list[str]]] = [
    ("mercadona", "Mercadona", "#10b981", ["mercadona"]),
    ("bonarea", "Gasolinera Bonárea", "#f59e0b", ["bonarea"]),
    ("john_pye", "John Pye", "#38bdf8", ["john pye", "jhon pye"]),
    ("paypal", "PayPal", "#0070ba", ["paypal"]),
    (
        "supermercado_otros",
        "Otros Supermercados & Snacks",
        "#84cc16",
        [
            "sabeco",
            "frutos secos",
            "el rincon",
            "sweets and game",
            "carrefour",
            "dia",
            "lidl",
            "alcampo",
            "eroski",
            "supermercado",
        ],
    ),
    (
        "restauracion_bares",
        "Restauración & Bares",
        "#ec4899",
        [
            "bar ",
            "bar restaur",
            "bar cuco",
            "bar arqueros",
            "cafe",
            "tribu",
            "ginger",
            "jarana",
            "koi asian",
            "baldo",
            "fox taver",
            "gentlebar",
            "santagloria",
            "tal y cual",
            "via augusta",
            "restaurante",
            "pizzer",
            "cerveceria",
            "heladeria",
            "burguer",
            "burger",
        ],
    ),
    ("bizums_amigos", "Bizums a Amigos (Cenas/Ocio)", "#8b5cf6", ["bizum a favor"]),
    (
        "transporte_otros",
        "Otros Transportes & Movilidad",
        "#eab308",
        ["bicicletas zara", "renfe", "uber", "cabify", "taxi", "avanza", "alsa", "metro"],
    ),
    (
        "ocio_deportes",
        "Ocio, Deporte y Eventos",
        "#06b6d4",
        ["kinepolis", "cdm", "helis play", "real zaragoza", "cine", "teatro", "padel", "concierto", "entrada"],
    ),
    (
        "suscripciones_fijas",
        "Suscripciones Fijas",
        "#3b82f6",
        ["unicef", "fitness park", "cursor", "spotify", "netflix", "apple", "google storage", "prime"],
    ),
    ("ayuntamiento_de", "Ayuntamiento De", "#64748b", ["ayuntamiento"]),
    ("dgt", "DGT", "#64748b", ["dgt"]),
    ("cajero_efectivo", "Efectivo / Cajero", "#14b8a6", ["cajero", "retirada de efectivo"]),
    (
        "compras_shopping",
        "Compras & Shopping",
        "#6366f1",
        [
            "slavquima",
            "trekkinn",
            "c.c. plaza",
            "loom",
            "amazon",
            "aliexpress",
            "zara",
            "pull and bear",
            "shein",
            "tienda",
            "el corte ingles",
        ],
    ),
]

CATEGORY_METADATA: dict[str, dict[str, str]] = {
    rule[0]: {"name": rule[1], "color": rule[2]} for rule in CATEGORY_RULES
}
CATEGORY_METADATA["otros"] = {"name": "Otros Gastos", "color": "#94a3b8"}


def clean_concept_for_display(concept: str) -> str:
    """Limpia y normaliza el concepto de una transacción bancaria para lectura clara."""
    c = str(concept).strip()
    c_low = c.lower()
    if "paypal" in c_low:
        m = re.search(r"Nº\s*Recibo\s*[\d\s]+([A-Za-z0-9]+)", c, flags=re.IGNORECASE)
        ref = m.group(1).upper() if m else ""
        return f"Pago PayPal (Ref. {ref})" if ref else "Pago PayPal"
    if "unicef" in c_low:
        return "Recibo Fundación UNICEF"
    if "kinepolis" in c_low:
        return "Kinépolis"
    if "c.d.m." in c_low or "cdm " in c_low:
        return "CDM Gran Vía"
    if "bizum a favor de" in c_low:
        return re.sub(r"\s+\d{2}/\d{2}/\d{4}.*", "", c).strip()
    if "bizum de" in c_low:
        return re.sub(r"\s+\d{2}/\d{2}/\d{4}.*", "", c).strip()
    if "bonarea" in c_low:
        return "Gasolinera Bonárea"
    if "mercadona" in c_low:
        return "Mercadona"
    if "john pye" in c_low or "jhon pye" in c_low:
        return "John Pye Auctions"

    # Eliminar números largos de recibo/mandato bancario si los hubiera
    cleaned = re.split(r"[,;]|\bNº\b|\bRef\b|\bMandato\b", c, flags=re.IGNORECASE)[0].strip()
    return cleaned if cleaned else c


def categorize_concept(concept: str) -> str:
    c = str(concept).lower()
    for cat_key, _, _, patterns in CATEGORY_RULES:
        if any(p in c for p in patterns):
            return cat_key
    # Si no se reconoce una categoría predefinida, usar el propio concepto de la transacción
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", c).strip("_")
    return clean[:40] if clean else "otros"


def parse_and_aggregate_excels_multimonth(
    files_data: list[tuple[str, bytes]],
) -> tuple[dict[tuple[int, int, str], dict[str, dict]], list[str]]:
    """Lee ficheros XLS y calcula los gastos agrupados por (año, mes, tipo_fuente),

    conservando el detalle de conceptos/transacciones agrupados por categoría.
    """
    parsed_dfs: list[pd.DataFrame] = []
    periods_and_sources: set[tuple[int, int, str]] = set()
    detected_sources: set[str] = set()

    for filename, content in files_data:
        try:
            df_raw = pd.read_excel(io.BytesIO(content), header=None)
        except Exception as e:
            logger.warning("No se pudo leer el fichero Excel %s: %s", filename, e)
            continue

        header_idx = None
        for idx, r in df_raw.head(25).iterrows():
            if r.astype(str).str.contains("FECHA OPERACIÓN", case=False).any():
                header_idx = idx
                break

        if header_idx is None:
            logger.warning("Fichero %s ignorado: no contiene la cabecera 'FECHA OPERACIÓN'", filename)
            continue

        try:
            df = pd.read_excel(io.BytesIO(content), skiprows=header_idx)
        except Exception as e:
            logger.warning("Error leyendo filas del fichero %s: %s", filename, e)
            continue

        df.columns = [str(c).strip().upper() for c in df.columns]
        if "FECHA OPERACIÓN" not in df.columns or "IMPORTE EUR" not in df.columns:
            continue

        source_type = "ACCOUNT" if "SALDO" in df.columns else "CARD"
        df["_source_type"] = source_type
        if source_type == "ACCOUNT":
            detected_sources.add("Cuenta Corriente")
        else:
            detected_sources.add("Tarjeta de Crédito")

        df["FECHA OPERACIÓN"] = pd.to_datetime(df["FECHA OPERACIÓN"], format="%d/%m/%Y", errors="coerce")
        df = df.dropna(subset=["FECHA OPERACIÓN"]).copy()

        for d in df["FECHA OPERACIÓN"]:
            periods_and_sources.add((d.year, d.month, source_type))

        parsed_dfs.append(df)

    results: dict[tuple[int, int, str], dict[str, dict]] = {}

    for year, month, src in sorted(periods_and_sources):
        rows: list[dict] = []
        has_renting_charge = False
        renting_charge_amt = 0.0
        has_renting_bonus = False

        for df in parsed_dfs:
            mask = (
                (df["_source_type"] == src)
                & (df["FECHA OPERACIÓN"].dt.year == year)
                & (df["FECHA OPERACIÓN"].dt.month == month)
            )
            month_df = df[mask]

            for _, row in month_df.iterrows():
                raw_concept = str(row.get("CONCEPTO", "")).strip()
                try:
                    amount = float(row.get("IMPORTE EUR", 0.0))
                except (ValueError, TypeError):
                    continue

                c_low = raw_concept.lower()
                clean_concept = clean_concept_for_display(raw_concept)

                if src == "ACCOUNT":
                    # 1. Traspasos internos propios y nómina geograma -> excluir
                    if "nomina geograma" in c_low or "juan francisco perez" in c_low:
                        continue

                    # 2. Liquidación de tarjeta -> excluir
                    if "liquidacion de las tarjetas" in c_low:
                        continue

                    # 3. Renting Tecnológico
                    if "renting tec" in c_low and amount < 0:
                        has_renting_charge = True
                        renting_charge_amt = abs(amount)
                        continue
                    if "bonificacion de campaña" in c_low and amount > 0:
                        if abs(amount - 24.99) < 0.05:
                            has_renting_bonus = True
                            continue

                    # 4. Bizums entrantes de personas (reembolsos)
                    if amount > 0:
                        if "bizum de" in c_low:
                            rows.append({
                                "category": "bizums_amigos",
                                "concept": clean_concept,
                                "amount": -amount,
                            })
                        continue

                    # 5. Gasto ordinario negativo
                    cat = categorize_concept(raw_concept)
                    rows.append({
                        "category": cat,
                        "concept": clean_concept,
                        "amount": abs(amount),
                    })

                else:  # src == "CARD"
                    cat = categorize_concept(raw_concept)
                    if amount < 0:
                        rows.append({
                            "category": cat,
                            "concept": clean_concept,
                            "amount": abs(amount),
                        })
                    elif amount > 0:
                        rows.append({
                            "category": cat,
                            "concept": clean_concept,
                            "amount": -abs(amount),
                        })

        if has_renting_charge and not has_renting_bonus:
            rows.append({
                "category": "suscripciones_fijas",
                "concept": "Cargo Renting Tecnológico",
                "amount": renting_charge_amt,
            })

        # Agrupar por categoría y dentro de ella por concepto
        category_groups: dict[str, dict] = {}
        for r in rows:
            cat = r["category"]
            c_name = r["concept"]
            amt = r["amount"]

            if cat not in category_groups:
                category_groups[cat] = {"amount": 0.0, "items_map": {}}

            category_groups[cat]["amount"] += amt

            if c_name not in category_groups[cat]["items_map"]:
                category_groups[cat]["items_map"][c_name] = {"concept": c_name, "amount": 0.0, "count": 0}

            category_groups[cat]["items_map"][c_name]["amount"] += amt
            category_groups[cat]["items_map"][c_name]["count"] += 1

        cleaned_totals: dict[str, dict] = {}
        for cat, data in category_groups.items():
            if data["amount"] > 0.009:
                items_list = []
                for it in sorted(data["items_map"].values(), key=lambda x: x["amount"], reverse=True):
                    if abs(it["amount"]) > 0.009:
                        items_list.append({
                            "concept": it["concept"],
                            "amount": round(it["amount"], 2),
                            "count": it["count"],
                        })
                cleaned_totals[cat] = {
                    "amount": round(data["amount"], 2),
                    "items": items_list,
                }

        if cleaned_totals:
            results[(year, month, src)] = cleaned_totals

    return results, sorted(detected_sources)


def import_expenses_for_month(
    db: Session,
    files_data: list[tuple[str, bytes]],
    current_year: int,
    current_month: int,
) -> MonthlyExpensesResponse:
    """Calcula y persiste los snapshots de gastos para los meses detectados en los Excel,

    guardando la relación con el detalle de conceptos en monthly_category_expense_items.
    """
    results_by_period_and_source, detected_sources = parse_and_aggregate_excels_multimonth(files_data)

    existing_stmt = select(MonthlyCategoryExpense.year, MonthlyCategoryExpense.month).distinct()
    existing_periods: set[tuple[int, int]] = {tuple(row) for row in db.execute(existing_stmt).all()}

    all_periods: set[tuple[int, int]] = {(year, month) for (year, month, _) in results_by_period_and_source.keys()}

    imported_month_set: set[str] = set()
    skipped_month_set: set[str] = set()

    for year, month in sorted(all_periods):
        if (year, month) in existing_periods:
            logger.info("Mes %02d/%d ya existe en la BD. Se omite para no sobrescribir.", month, year)
            skipped_month_set.add(f"{month:02d}/{year}")
            continue

        imported_month_set.add(f"{month:02d}/{year}")

        # Insertar todas las categorías e ítems de este lote para este mes nuevo
        for (y, m, src), cat_map in results_by_period_and_source.items():
            if y == year and m == month:
                for cat_key, cat_data in cat_map.items():
                    expense_rec = MonthlyCategoryExpense(
                        year=year,
                        month=month,
                        category=cat_key,
                        source_type=src,
                        amount=cat_data["amount"],
                    )
                    db.add(expense_rec)
                    db.flush()

                    for it in cat_data["items"]:
                        db.add(
                            MonthlyCategoryExpenseItem(
                                expense_id=expense_rec.id,
                                concept=it["concept"],
                                amount=it["amount"],
                                count=it["count"],
                            )
                        )

    db.commit()
    return get_monthly_expenses(
        db,
        current_year,
        current_month,
        imported_months=sorted(list(imported_month_set)),
        skipped_months=sorted(list(skipped_month_set)),
        imported_sources=detected_sources,
    )


def get_monthly_expenses(
    db: Session,
    year: int,
    month: int,
    imported_months: list[str] | None = None,
    skipped_months: list[str] | None = None,
    imported_sources: list[str] | None = None,
) -> MonthlyExpensesResponse:
    """Devuelve los gastos de un mes desglosados por categoría con el detalle expandible de transacciones."""
    stmt = (
        select(MonthlyCategoryExpense)
        .where(
            MonthlyCategoryExpense.year == year,
            MonthlyCategoryExpense.month == month,
        )
    )
    records = list(db.scalars(stmt).all())

    # Agrupar importes y detalles por categoría sumando todas las fuentes registradas
    category_totals: dict[str, float] = {}
    category_items: dict[str, dict[str, dict]] = {}
    db_sources: set[str] = set()

    for r in records:
        category_totals[r.category] = category_totals.get(r.category, 0.0) + float(r.amount)

        if r.category not in category_items:
            category_items[r.category] = {}

        for it in r.items:
            c_name = it.concept
            if c_name not in category_items[r.category]:
                category_items[r.category][c_name] = {"concept": c_name, "amount": 0.0, "count": 0}
            category_items[r.category][c_name]["amount"] += float(it.amount)
            category_items[r.category][c_name]["count"] += it.count

        if r.source_type == "ACCOUNT":
            db_sources.add("Cuenta Corriente")
        elif r.source_type == "CARD":
            db_sources.add("Tarjeta de Crédito")
        else:
            db_sources.add(r.source_type)

    total_amount = sum(category_totals.values())
    categories: list[CategoryExpenseItem] = []

    sorted_cats = sorted(category_totals.items(), key=lambda item: item[1], reverse=True)

    for cat_key, amt in sorted_cats:
        meta = CATEGORY_METADATA.get(cat_key, {"name": cat_key.replace("_", " ").title(), "color": "#94a3b8"})
        pct = round((amt / total_amount * 100), 2) if total_amount > 0 else 0.0

        raw_items = list(category_items.get(cat_key, {}).values())
        sorted_items = sorted(raw_items, key=lambda x: x["amount"], reverse=True)
        detail_items = [
            ExpenseItemDetail(
                concept=it["concept"],
                amount=round(it["amount"], 2),
                count=it["count"],
            )
            for it in sorted_items
        ]

        categories.append(
            CategoryExpenseItem(
                category=cat_key,
                category_name=meta["name"],
                color=meta["color"],
                amount=round(amt, 2),
                percentage=pct,
                items=detail_items,
            )
        )

    sources_to_report = sorted(list(db_sources))

    return MonthlyExpensesResponse(
        year=year,
        month=month,
        total_amount=round(total_amount, 2),
        categories=categories,
        has_expenses=len(records) > 0,
        imported_months=imported_months or [],
        skipped_months=skipped_months or [],
        imported_sources=sources_to_report,
    )
