"""Generate a filterable Excel availability table with dynamically recalculated remaining days."""

from datetime import date
from pathlib import Path

import pandas as pd
from xlsxwriter.utility import xl_col_to_name

from src.expiration import days_remaining, paris_today
from src.tracker import ContentResult

COLUMNS = ['Titre', 'Sous-genre', 'Service', 'Jours restants', "Disponible jusqu'au",
           'Épisode à reprendre', 'Épisodes restants', 'Durée', 'Catégorie',
           "Dans l'offre", 'URL myCANAL', 'Content ID', 'Fin de disponibilité', 'Statut']


DAYS_FORMULA = (
    '=IF([[#This Row],[Fin de disponibilité]]="","",'
    '[[#This Row],[Fin de disponibilité]]-TODAY())'
)


def excel_duration(result: ContentResult) -> float | str:
    item = result.item
    if item.content_type == 'folder':
        return (result.duration_minutes / 1440
                if result.episodes_remaining is not None
                and result.duration_minutes is not None else '')
    # Playlist duration is current; the verified detail movie duration is a fallback.
    minutes = item.movie_duration_minutes
    if minutes is None:
        minutes = result.duration_minutes
        if (minutes is not None and item.content_type == 'VoD'
                and item.duration_ms is not None and item.duration_ms >= 60_000):
            minutes = item.duration_ms // 60_000
    if minutes is None or minutes <= 0:
        return ''
    return minutes / 1440


def build_dataframe(results: list[ContentResult], today: date | None = None) -> pd.DataFrame:
    today = today or paris_today()
    records = []
    for result in results:
        item = result.item
        records.append({
            'Titre': item.title,
            'Sous-genre': result.subgenre,
            'Service': item.service,
            'Jours restants': days_remaining(result.expiration, today),
            "Disponible jusqu'au": result.availability_text,
            'Épisode à reprendre': result.resume_episode,
            'Épisodes restants': result.episodes_remaining,
            'Durée': excel_duration(result),
            'Catégorie': item.subtitle,
            "Dans l'offre": None if item.in_offer is None else ('Oui' if item.in_offer else 'Non'),
            'URL myCANAL': item.web_url,
            'Content ID': item.content_id,
            'Fin de disponibilité': result.expiration,
            'Statut': result.status,
        })
    frame = pd.DataFrame(records, columns=COLUMNS)
    frame['Jours restants'] = pd.array(frame['Jours restants'], dtype='Int64')
    frame['Épisodes restants'] = pd.array(frame['Épisodes restants'], dtype='Int64')
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
