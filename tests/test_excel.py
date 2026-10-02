from dataclasses import replace
from datetime import date, timedelta
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from mycanal_expiry_tracker.excel import build_dataframe, write_excel
from mycanal_expiry_tracker.tracker import ContentResult

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def test_sorting_and_recalculation(item):
    results = [ContentResult(item, None, 'Date inconnue'),
               ContentResult(item, date(2026, 11, 2), 'OK'),
               ContentResult(item, date(2026, 10, 1), 'OK')]
    frame = build_dataframe(results, date(2026, 10, 1))
    assert frame['Fin de disponibilité'].tolist() == [date(2026, 10, 1), date(2026, 11, 2), None]
    assert frame['Jours restants'].iloc[:2].tolist() == [0, 32]
    assert build_dataframe(results, date(2026, 10, 2))['Jours restants'].iloc[0] == -1


def test_excel_native_features_and_untrusted_text(tmp_path, item):
    today = date(2026, 10, 1)
    hostile_item = replace(item, title='=HYPERLINK("https://evil.test","click")', service='=1+1')
    results = [ContentResult(hostile_item, today + timedelta(days=i), 'OK', '=2+2')
               for i in [-1, 0, 2, 3, 7, 8, 30, 31]]
    results.append(ContentResult(item, None, 'Date inconnue'))
    path = tmp_path / 'report.xlsx'
    write_excel(results, path, today)
    with ZipFile(path) as book:
        sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
        table = ET.fromstring(book.read('xl/tables/table1.xml'))
        assert table.attrib['ref'] == 'A1:N10'
        assert table.find('m:autoFilter', NS).attrib['ref'] == 'A1:N10'
        assert sheet.find('m:sheetViews/m:sheetView/m:pane', NS).attrib['ySplit'] == '1'
        assert sheet.find('m:conditionalFormatting', NS).attrib['sqref'] == 'A2:N10'
        formulas = [e.text for e in sheet.findall('.//m:cfRule/m:formula', NS)]
        assert formulas == ['AND(ISNUMBER($D2),$D2<0)',
                            'AND(ISNUMBER($D2),$D2=0)',
                            'AND(ISNUMBER($D2),$D2>=1,$D2<=2)',
                            'AND(ISNUMBER($D2),$D2>=3,$D2<=7)',
                            'AND(ISNUMBER($D2),$D2>=8,$D2<=30)']
        styles_xml = ET.fromstring(book.read('xl/styles.xml'))
        dxfs = styles_xml.find('m:dxfs', NS)
        for rule, background, foreground in zip(
            sheet.findall('.//m:cfRule', NS),
            ['FF333333', 'FF9C0006', 'FFFFC7CE', 'FFF4B183', 'FFFFEB9C'],
            ['FFD9D9D9', 'FFFFFFFF', None, None, None],
        ):
            style = dxfs[int(rule.attrib['dxfId'])]
            assert style.find('m:fill/m:patternFill/m:bgColor', NS).attrib['rgb'] == background
            if foreground:
                assert style.find('m:font/m:color', NS).attrib['rgb'] == foreground
        cell_formulas = sheet.findall('.//m:c/m:f', NS)
        assert len(cell_formulas) == len(results)
        expected = 'IF([[#This Row],[Fin de disponibilité]]="","",[[#This Row],[Fin de disponibilité]]-TODAY())'
        assert all(formula.text == expected for formula in cell_formulas)
        assert table.find('.//m:calculatedColumnFormula', NS).text == expected
        assert all(cell.attrib['r'].startswith('D')
                   for cell in sheet.findall('.//m:c', NS) if cell.find('m:f', NS) is not None)
        calculation = ET.fromstring(book.read('xl/workbook.xml')).find('m:calcPr', NS)
        assert calculation.attrib['fullCalcOnLoad'] == '1'
        assert len(sheet.findall('m:hyperlinks/m:hyperlink', NS)) == 9
        assert all(link.attrib['ref'].startswith('K')
                   for link in sheet.findall('m:hyperlinks/m:hyperlink', NS))
        hidden = [c for c in sheet.findall('m:cols/m:col', NS) if c.attrib.get('hidden') == '1']
        assert len(hidden) == 1 and hidden[0].attrib['min'] == '12'
        styles = book.read('xl/styles.xml').decode()
        assert 'dd/mm/yyyy' in styles
        # A known date is an Excel numeric value; an unknown date/day is blank.
        assert sheet.find('.//m:c[@r="M2"]/m:v', NS) is not None
        assert sheet.find('.//m:c[@r="M10"]/m:v', NS) is None
        assert sheet.find('.//m:c[@r="D10"]/m:v', NS).text is None
        assert 'HYPERLINK' in book.read('xl/sharedStrings.xml').decode()


def test_empty_export_has_table(tmp_path):
    path = tmp_path / 'empty.xlsx'
    write_excel([], path)
    with ZipFile(path) as book:
        table = ET.fromstring(book.read('xl/tables/table1.xml'))
        assert table.attrib['ref'] == 'A1:N2'


def test_subgenre_column_preserves_duplicate_category(tmp_path, item):
    results = [ContentResult(item, None, 'Date inconnue', item.subtitle),
               ContentResult(item, None, 'Date inconnue')]
    path = tmp_path / 'subgenre.xlsx'
    frame = write_excel(results, path)
    assert frame.columns.tolist() == [
        'Titre', 'Sous-genre', 'Service', 'Jours restants', "Disponible jusqu'au",
        'Épisode à reprendre', 'Épisodes restants', 'Durée', 'Catégorie', "Dans l'offre", 'URL myCANAL', 'Content ID',
        'Fin de disponibilité', 'Statut',
    ]
    assert frame['Catégorie'].tolist() == [item.subtitle, item.subtitle]
    assert frame['Sous-genre'].tolist() == [item.subtitle, '']
    with ZipFile(path) as book:
        table = ET.fromstring(book.read('xl/tables/table1.xml'))
        headers = [c.attrib['name'] for c in table.findall('m:tableColumns/m:tableColumn', NS)]
        assert headers == frame.columns.tolist()
        sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
        strings = ET.fromstring(book.read('xl/sharedStrings.xml'))
        for ref in ('I2', 'B2', 'I3'):
            index = int(sheet.find(f'.//m:c[@r="{ref}"]/m:v', NS).text)
            assert ''.join(strings[index].itertext()) == item.subtitle
        assert sheet.find('.//m:c[@r="B3"]/m:v', NS) is None


def test_duration_is_numeric_and_availability_is_text(tmp_path, item):
    result = ContentResult(item, date(2026, 9, 30), 'OK', duration_minutes=107,
                           availability_text='mercredi 30 septembre 23h59')
    path = tmp_path / 'presentation.xlsx'
    frame = write_excel([result], path)
    assert frame['Durée'].tolist() == [107 / 1440]
    assert frame["Disponible jusqu'au"].tolist() == ['mercredi 30 septembre 23h59']
    with ZipFile(path) as book:
        sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
        strings = ET.fromstring(book.read('xl/sharedStrings.xml'))
        duration = sheet.find('.//m:c[@r="H2"]', NS)
        assert duration.attrib.get('t', 'n') == 'n'
        assert float(duration.find('m:v', NS).text) == pytest.approx(107 / 1440)
        styles = ET.fromstring(book.read('xl/styles.xml'))
        style = styles.find('m:cellXfs', NS)[int(duration.attrib['s'])]
        number_format = styles.find(
            f'm:numFmts/m:numFmt[@numFmtId="{style.attrib["numFmtId"]}"]', NS,
        )
        assert number_format.attrib['formatCode'] == '[h]" h "mm" min"'
        for ref, expected in [('E2', result.availability_text)]:
            cell = sheet.find(f'.//m:c[@r="{ref}"]', NS)
            assert cell.attrib['t'] == 's'
            assert ''.join(strings[int(cell.find('m:v', NS).text)].itertext()) == expected


def test_playlist_duration_has_priority_and_folders_stay_empty(item):
    movie = replace(item, duration_ms=5880000)
    folder = replace(movie, content_type='folder')
    results = [ContentResult(movie, None, 'Date inconnue', duration_minutes=133),
               ContentResult(folder, None, 'Date inconnue', duration_minutes=133)]
    assert build_dataframe(results)['Durée'].tolist() == [98 / 1440, '']


def test_non_movie_playlist_duration_is_not_used(item):
    documentary = replace(item, subtitle='Doc. Nature', duration_ms=5880000)
    assert build_dataframe([ContentResult(documentary, None, 'Date inconnue')])['Durée'].iloc[0] == ''


def test_series_backlog_columns_and_numeric_duration(tmp_path, item):
    series = replace(item, content_type='folder', title='Pikachu')
    results = [ContentResult(series, date(2026, 9, 30), 'OK', duration_minutes=1697,
                             resume_episode='S3E3', episodes_remaining=27),
               ContentResult(item, None, 'Date inconnue')]
    path = tmp_path / 'series.xlsx'
    frame = write_excel(results, path)
    assert frame['Épisode à reprendre'].tolist() == ['S3E3', '']
    assert frame['Épisodes restants'].iloc[0] == 27
    with ZipFile(path) as book:
        sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
        count = sheet.find('.//m:c[@r="G2"]', NS)
        duration = sheet.find('.//m:c[@r="H2"]', NS)
        assert count.attrib.get('t', 'n') == duration.attrib.get('t', 'n') == 'n'
        assert int(count.find('m:v', NS).text) == 27
        assert float(duration.find('m:v', NS).text) == pytest.approx(1697 / 1440)
        for ref in ('F3', 'G3', 'H3'):
            assert sheet.find(f'.//m:c[@r="{ref}"]/m:v', NS) is None
