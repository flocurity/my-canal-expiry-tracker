from dataclasses import replace
from datetime import date, timedelta
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from src.excel import build_dataframe, write_excel
from src.tracker import ContentResult

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
        assert table.attrib['ref'] == 'A1:L10'
        assert table.find('m:autoFilter', NS).attrib['ref'] == 'A1:L10'
        assert sheet.find('m:sheetViews/m:sheetView/m:pane', NS).attrib['ySplit'] == '1'
        assert sheet.find('m:conditionalFormatting', NS).attrib['sqref'] == 'A2:L10'
        formulas = [e.text for e in sheet.findall('.//m:cfRule/m:formula', NS)]
        assert formulas == ['AND(ISNUMBER($F2),$F2<=2)',
                            'AND(ISNUMBER($F2),$F2>=3,$F2<=7)',
                            'AND(ISNUMBER($F2),$F2>=8,$F2<=30)']
        cell_formulas = sheet.findall('.//m:c/m:f', NS)
        assert len(cell_formulas) == len(results)
        expected = 'IF([[#This Row],[Fin de disponibilité]]="","",[[#This Row],[Fin de disponibilité]]-TODAY())'
        assert all(formula.text == expected for formula in cell_formulas)
        assert table.find('.//m:calculatedColumnFormula', NS).text == expected
        assert all(cell.attrib['r'].startswith('F')
                   for cell in sheet.findall('.//m:c', NS) if cell.find('m:f', NS) is not None)
        calculation = ET.fromstring(book.read('xl/workbook.xml')).find('m:calcPr', NS)
        assert calculation.attrib['fullCalcOnLoad'] == '1'
        assert len(sheet.findall('m:hyperlinks/m:hyperlink', NS)) == 9
        assert all(link.attrib['ref'].startswith('H')
                   for link in sheet.findall('m:hyperlinks/m:hyperlink', NS))
        hidden = [c for c in sheet.findall('m:cols/m:col', NS) if c.attrib.get('hidden') == '1']
        assert len(hidden) == 1 and hidden[0].attrib['min'] == '9'
        styles = book.read('xl/styles.xml').decode()
        assert 'dd/mm/yyyy' in styles
        # A known date is an Excel numeric value; an unknown date/day is blank.
        assert sheet.find('.//m:c[@r="E2"]/m:v', NS) is not None
        assert sheet.find('.//m:c[@r="E10"]/m:v', NS) is None
        assert sheet.find('.//m:c[@r="F10"]/m:v', NS).text is None
        assert 'HYPERLINK' in book.read('xl/sharedStrings.xml').decode()


def test_empty_export_has_table(tmp_path):
    path = tmp_path / 'empty.xlsx'
    write_excel([], path)
    with ZipFile(path) as book:
        table = ET.fromstring(book.read('xl/tables/table1.xml'))
        assert table.attrib['ref'] == 'A1:L2'


def test_subgenre_column_preserves_duplicate_category(tmp_path, item):
    results = [ContentResult(item, None, 'Date inconnue', item.subtitle),
               ContentResult(item, None, 'Date inconnue')]
    path = tmp_path / 'subgenre.xlsx'
    frame = write_excel(results, path)
    assert frame.columns.tolist() == [
        'Titre', 'Catégorie', 'Sous-genre', 'Service', 'Fin de disponibilité',
        'Jours restants', "Dans l'offre", 'URL myCANAL', 'Content ID', 'Statut',
        'Durée', 'Disponible jusqu’au',
    ]
    assert frame['Catégorie'].tolist() == [item.subtitle, item.subtitle]
    assert frame['Sous-genre'].tolist() == [item.subtitle, '']
    with ZipFile(path) as book:
        table = ET.fromstring(book.read('xl/tables/table1.xml'))
        headers = [c.attrib['name'] for c in table.findall('m:tableColumns/m:tableColumn', NS)]
        assert headers == frame.columns.tolist()
        sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
        strings = ET.fromstring(book.read('xl/sharedStrings.xml'))
        for ref in ('B2', 'C2', 'B3'):
            index = int(sheet.find(f'.//m:c[@r="{ref}"]/m:v', NS).text)
            assert ''.join(strings[index].itertext()) == item.subtitle
        assert sheet.find('.//m:c[@r="C3"]/m:v', NS) is None


def test_new_presentation_columns_are_exported_as_text(tmp_path, item):
    result = ContentResult(item, date(2026, 9, 30), 'OK', duration='1 h 47 min',
                           availability_text='mercredi 30 septembre 23h59')
    path = tmp_path / 'presentation.xlsx'
    frame = write_excel([result], path)
    assert frame['Durée'].tolist() == ['1 h 47 min']
    assert frame['Disponible jusqu’au'].tolist() == ['mercredi 30 septembre 23h59']
    with ZipFile(path) as book:
        sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
        strings = ET.fromstring(book.read('xl/sharedStrings.xml'))
        for ref, expected in [('K2', result.duration), ('L2', result.availability_text)]:
            cell = sheet.find(f'.//m:c[@r="{ref}"]', NS)
            assert cell.attrib['t'] == 's'
            assert ''.join(strings[int(cell.find('m:v', NS).text)].itertext()) == expected
