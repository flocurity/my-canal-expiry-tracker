"""Generate a filterable Excel availability table with dynamically recalculated remaining days."""

from datetime import date
from pathlib import Path
import os
from tempfile import TemporaryDirectory

import pandas as pd
from xlsxwriter.utility import xl_col_to_name

from mycanal_expiry_tracker.expiration import days_remaining, paris_today
from mycanal_expiry_tracker.report import ReportRow
from mycanal_expiry_tracker.cache import snapshot_data
from mycanal_hodor_core.timing import timeit

COLUMNS = ['Titre', 'Sous-genre', 'Service', 'Jours restants', "Disponible jusqu'au",
           'Épisode à reprendre', 'Épisodes restants', 'Durée', 'Catégorie',
           "Dans l'offre", 'URL myCANAL', 'Content ID', 'Fin de disponibilité', 'Statut']


DAYS_FORMULA = (
    '=IF([[#This Row],[Fin de disponibilité]]="","",'
    '[[#This Row],[Fin de disponibilité]]-TODAY())'
)


def build_dataframe(results: list[ReportRow], today: date | None = None) -> pd.DataFrame:
    today = today or paris_today()
    records = []
    # Preserve date ordering for legacy date-only results, and order timestamp
    # groups within the same local date by their exact expiration.
    results = sorted(results, key=lambda result: (
        result.expiration is None, result.expiration or date.max,
        result.availability_end_date if result.availability_end_date is not None else float('-inf'),
    ))
    for result in results:
        records.append({
            'Titre': result.title,
            'Sous-genre': result.subgenre,
            'Service': result.service,
            'Jours restants': days_remaining(result.expiration, today),
            "Disponible jusqu'au": result.availability_text,
            'Épisode à reprendre': result.resume_episode,
            'Épisodes restants': result.episodes_remaining,
            'Durée': result.duration_minutes / 1440 if result.duration_minutes is not None else '',
            'Catégorie': result.category,
            "Dans l'offre": None if result.in_offer is None else ('Oui' if result.in_offer else 'Non'),
            'URL myCANAL': result.public_url,
            'Content ID': result.content_id,
            'Fin de disponibilité': result.expiration,
            'Statut': result.status,
        })
    frame = pd.DataFrame(records, columns=COLUMNS)
    frame['Jours restants'] = pd.array(frame['Jours restants'], dtype='Int64')
    frame['Épisodes restants'] = pd.array(frame['Épisodes restants'], dtype='Int64')
    return frame.sort_values(['Fin de disponibilité', 'Jours restants'], na_position='last',
                             kind='stable').reset_index(drop=True)


def _write_excel(
    results: list[ReportRow], path: Path, today: date | None = None,
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
        days_column = COLUMNS.index('Jours restants')
        duration_format = workbook.add_format({'num_format': '[h]" h "mm" min"'})
        formats = {'Fin de disponibilité': date_format, 'Jours restants': integer_format,
                   'Durée': duration_format, 'Épisodes restants': integer_format}
        for name, fmt in formats.items():
            columns[COLUMNS.index(name)]['format'] = fmt
        columns[days_column]['formula'] = DAYS_FORMULA
        # Excel requires at least one data row even for an empty playlist table.
        last_row = max(1, len(frame))
        sheet.add_table(0, 0, last_row, len(COLUMNS) - 1, {
            'name': 'MaListe', 'columns': columns, 'style': 'Table Style Medium 2',
        })
        # Supply useful cached previews; Excel recalculates the formula on opening.
        for row, value in enumerate(frame['Jours restants'], start=1):
            sheet.write_formula(row, days_column, DAYS_FORMULA, integer_format,
                                '' if pd.isna(value) else int(value))
        if frame.empty:
            sheet.write_formula(1, days_column, DAYS_FORMULA, integer_format, '')
        sheet.freeze_panes(1, 0)
        for column, name in enumerate(COLUMNS):
            lengths = [len(name), *(len(str(value)) for value in frame[name] if pd.notna(value))]
            width = 15 if name == 'Durée' else min(55, max(lengths) + 2)
            sheet.set_column(column, column, width, formats.get(name),
                             {'hidden': name == 'Content ID'})
        for row, url in enumerate(frame['URL myCANAL'], start=1):
            if isinstance(url, str) and url.startswith('https://') and len(url) <= 2079:
                sheet.write_url(row, COLUMNS.index('URL myCANAL'), url)
        if len(frame):
            days = f'${xl_col_to_name(days_column)}2'
            rules = [
                (f'{days}<0', {'bg_color': '#333333', 'font_color': '#D9D9D9'}),
                (f'{days}=0', {'bg_color': '#9C0006', 'font_color': '#FFFFFF'}),
                (f'{days}>=1,{days}<=2', {'bg_color': '#FFC7CE'}),
                (f'{days}>=3,{days}<=7', {'bg_color': '#F4B183'}),
                (f'{days}>=8,{days}<=30', {'bg_color': '#FFEB9C'}),
            ]
            for condition, style in rules:
                formula = f'AND(ISNUMBER({days}),{condition})'
                sheet.conditional_format(1, 0, len(frame), len(COLUMNS) - 1, {
                    'type': 'formula', 'criteria': '=' + formula,
                    'format': workbook.add_format(style),
                })
    return frame


@timeit()
def write_excel(results: list[ReportRow], path: Path, today: date | None = None,
                *, secrets: tuple[str, ...] = ()) -> pd.DataFrame:
    snapshot_data(results, secrets)
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.excel-', dir=path.parent) as temporary:
        staged = Path(temporary) / 'report.xlsx'
        frame = _write_excel(results, staged, today)
        os.replace(staged, path)
    return frame
