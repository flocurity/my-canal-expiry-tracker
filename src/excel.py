"""Generate a filterable Excel availability table with dynamically recalculated remaining days."""

from datetime import date
from pathlib import Path

import pandas as pd

from src.expiration import days_remaining, paris_today
from src.tracker import ContentResult

COLUMNS = ['Titre', 'Catégorie', 'Sous-genre', 'Service', 'Fin de disponibilité', 'Jours restants',
           "Dans l'offre", 'URL myCANAL', 'Content ID', 'Statut', 'Durée', 'Disponible jusqu’au']


DAYS_FORMULA = (
    '=IF([[#This Row],[Fin de disponibilité]]="","",'
    '[[#This Row],[Fin de disponibilité]]-TODAY())'
)


def build_dataframe(results: list[ContentResult], today: date | None = None) -> pd.DataFrame:
    today = today or paris_today()
    records = []
    for result in results:
        item = result.item
        records.append([
            item.title, item.subtitle, result.subgenre, item.service, result.expiration,
            days_remaining(result.expiration, today),
            None if item.in_offer is None else ('Oui' if item.in_offer else 'Non'),
            item.web_url, item.content_id, result.status, result.duration, result.availability_text,
        ])
    frame = pd.DataFrame(records, columns=COLUMNS)
    frame['Jours restants'] = pd.array(frame['Jours restants'], dtype='Int64')
    return frame.sort_values(['Fin de disponibilité', 'Jours restants'], na_position='last',
                             kind='stable').reset_index(drop=True)


def write_excel(
    results: list[ContentResult], path: Path, today: date | None = None,
) -> pd.DataFrame:
    frame = build_dataframe(results, today)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine='xlsxwriter', date_format='dd/mm/yyyy',
                        datetime_format='dd/mm/yyyy', engine_kwargs={'options': {
                            'strings_to_formulas': False, 'strings_to_urls': False,
                        }}) as writer:
        frame.to_excel(writer, sheet_name='Ma liste', index=False, header=False, startrow=1)
        workbook = writer.book
        sheet = writer.sheets['Ma liste']
        date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
        integer_format = workbook.add_format({'num_format': '0'})
        columns = [{'header': name} for name in COLUMNS]
        columns[4]['format'] = date_format
        columns[5]['format'] = integer_format
        columns[5]['formula'] = DAYS_FORMULA
        # Excel requires at least one data row even for an empty playlist table.
        last_row = max(1, len(frame))
        sheet.add_table(0, 0, last_row, len(COLUMNS) - 1, {
            'name': 'MaListe', 'columns': columns, 'style': 'Table Style Medium 2',
        })
        # Supply useful cached previews; Excel recalculates the formula on opening.
        for row, value in enumerate(frame['Jours restants'], start=1):
            sheet.write_formula(row, 5, DAYS_FORMULA, integer_format,
                                '' if pd.isna(value) else int(value))
        if frame.empty:
            sheet.write_formula(1, 5, DAYS_FORMULA, integer_format, '')
        sheet.freeze_panes(1, 0)
        for column, name in enumerate(COLUMNS):
            lengths = [len(name), *(len(str(value)) for value in frame[name] if pd.notna(value))]
            width = min(55, max(lengths) + 2)
            fmt = date_format if column == 4 else integer_format if column == 5 else None
            sheet.set_column(column, column, width, fmt, {'hidden': column == 8})
        for row, url in enumerate(frame['URL myCANAL'], start=1):
            if isinstance(url, str) and url.startswith('https://') and len(url) <= 2079:
                sheet.write_url(row, 7, url)
        if len(frame):
            rules = [
                ('AND(ISNUMBER($F2),$F2<=2)', '#FFC7CE'),
                ('AND(ISNUMBER($F2),$F2>=3,$F2<=7)', '#F4B183'),
                ('AND(ISNUMBER($F2),$F2>=8,$F2<=30)', '#FFEB9C'),
            ]
            for formula, color in rules:
                sheet.conditional_format(1, 0, len(frame), len(COLUMNS) - 1, {
                    'type': 'formula', 'criteria': '=' + formula,
                    'format': workbook.add_format({'bg_color': color}),
                })
    return frame
