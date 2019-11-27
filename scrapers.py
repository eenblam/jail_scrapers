# !/usr/bin/env python3
"""This module does blah blah."""
import os
import sys
import time
from datetime import datetime, date, timezone
import urllib.parse
import requests
from bs4 import BeautifulSoup
from nameparser import HumanName
from airtable import Airtable
from tabulate import tabulate
import standardize


airtab = Airtable(os.environ['jail_scrapers_db'], 'intakes',
                  os.environ['AIRTABLE_API_KEY'])
table = [['function', 'minutes', 'new', 'total']]
muh_headers = {
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'}


def get_name(raw_name, this_dict):
    name = HumanName(raw_name)
    name.capitalize()
    this_dict['first name'] = name.first
    this_dict['last name'] = name.last
    this_dict['middle name'] = name.middle
    this_dict['suffix'] = name.suffix


def update_record(this_dict, soup, m, lea_parser=None, raw_lea=''):
    if this_dict['recent_text'] != m['fields']['recent_text']:
        this_dict['updated'] = True
        this_dict['html'] = soup.prettify()
        if lea_parser:
            lea_parser(raw_lea)
    airtab.update(m['id'], this_dict, typecast=True)


def wrap_it_up(jail, start_time, new_intakes, total_intakes, log_id, print_table=False):
    duration = round((time.time() - start_time) / 60, 2)
    log_dict = {f"{jail} downloads": new_intakes}
    log_dict[jail] = duration
    airtable_log = Airtable(os.environ['jail_scrapers_db'], 'log', os.environ['AIRTABLE_API_KEY'])
    airtable_log.update(log_id, log_dict)
    table.append([jail, duration, new_intakes, total_intakes])
    if print_table:
        print(tabulate(table, headers='firstrow', tablefmt='fancy_grid'))


def damn_it(error_message):
    print('Another fucking "Connection Error."\n', error_message)
    time.sleep(10)


def mcdc_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    root_url = 'http://mydcstraining.com/agencyinfo/MS/4360/inmate/'
    main_url = root_url + 'ICURRENT.HTM'
    page = requests.get(main_url, headers=muh_headers)
    soup = BeautifulSoup(page.text, 'html.parser')
    dk_rows = soup.find_all('tr')
    for dk_row in dk_rows:
        cells = dk_row.find_all('td')
        if len(cells) == 9:
            total_intakes += 1
            time.sleep(0.2)
            this_dict = {'jail': 'mcdc', 'linking': ['recfCbuUl7Xlyu3PC']}
            this_dict['link'] = root_url + dk_row.a.get('href')
            try:
                r = requests.get(this_dict['link'], headers=muh_headers)
            except requests.ConnectionError as err:
                damn_it(err)
                continue
            this_dict['charge_1'] = cells[8].string.replace('\xa0', '')
            if this_dict['charge_1'] == '18USC132518USC1325 ILLEGAL ENTRY-ALIEN':
                this_dict['charge_1_statute'] = '8 U.S.C. 1325'
                this_dict['charge_1_title'] = 'UNLAWFUL ENTRY'
            this_dict['bk'] = cells[2].string.replace('\xa0', '')
            this_dict['last_verified'] = (
                datetime.utcnow()
                .replace(tzinfo=timezone.utc)
                .strftime('%Y-%m-%d %H:%M')
            )
            this_dict['img_src'] = (
                this_dict['link'].replace('ICUD', 'ICUP').replace('HTM', 'jpg')
            )
            data = []
            soup = BeautifulSoup(r.text, 'html.parser')
            for string in soup.stripped_strings:
                data.append(str(string))
            try:
                this_dict['intake_number'] = data[1 + data.index('INTAKE #:')]
                this_dict['DOI'] = f"{data[1 + data.index('INTAKE DATE:')]} {data[1 + data.index('TIME:')]}"
                get_name(data[1 + data.index('Name:')], this_dict)
                this_dict['DOB'] = data[1 + data.index('DOB:')]
                this_dict['intake_age'] = int(data[1 + data.index('AGE:')])
                this_dict['race'] = standardize.mcdc_race(raw_race=data[1 + data.index('RACE:')])
                this_dict['sex'] = data[1 + data.index('SEX:')]
                if data[1 + data.index('OFF DATE:')] != '00/00/0000':
                    this_dict['DOO'] = data[1 + data.index('OFF DATE:')]
                this_dict['intake_case_number'] = data[1 + data.index('- Case#:')]
                this_dict['intake_bond_written'] = repr(
                    data[1 + data.index('WRITTEN BOND:')]
                ).replace('\xa0', ' ')
                this_dict['intake_bond_cash'] = repr(
                    data[1 + data.index('CASH BOND:')]
                ).replace('\xa0', ' ')
                blocks = soup.find_all('table')
                rows = blocks[9].find_all('tr')
                charges = []
                courts = []
                bond_ammounts = []
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) == 3:
                        charge_raw = cells[0].string.strip()
                        if ', ' in charge_raw:
                            charge = f"\"{charge_raw}\""
                        else:
                            charge = charge_raw
                        charges.append(charge)
                        court_raw = cells[1].string.strip()
                        if court_raw == 'OTHER COUR':
                            courts.append('OTHER COURT')
                        else:
                            courts.append(court_raw)
                        if cells[2].string:
                            amt = '$' + cells[2].string.strip()
                            bond_ammounts.append(amt)
                this_dict['charges'] = ', '.join(charges)
                this_dict['courts'] = ', '.join(courts)
                this_dict['bond_ammounts'] = '\n'.join(bond_ammounts)
                this_dict['recent_text'] = '\n'.join(data[data.index('Name:'):])
                raw_lea = data[1 + data.index('ARRESTING AGENCY:')]
                m = airtab.match(
                    'intake_number',
                    this_dict['intake_number'],
                    view='mcdc',
                    fields='recent_text',
                )
                if not m:
                    this_dict['LEA'] = standardize.mcdc_lea(raw_lea)
                    this_dict['html'] = soup.prettify()
                    attachments_array = []
                    image_url = {'url': this_dict['img_src']}
                    attachments_array.append(image_url)
                    this_dict['PHOTO'] = attachments_array
                    airtab.insert(this_dict, typecast=True)
                    new_intakes += 1
                else:
                    update_record(this_dict, soup, m, lea_parser=standardize.mcdc_lea, raw_lea=raw_lea)
            except ValueError:
                print('there was a value error for', this_dict['bk'])
    wrap_it_up('mcdc', start_time, new_intakes, total_intakes, log_id, print_table)


def prcdf_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    root_url = 'http://mydcstraining.com/agencyinfo/MS/0055/inmate/'
    main_url = root_url + 'ICURRENT.HTM'
    page = requests.get(main_url, headers=muh_headers)
    soup = BeautifulSoup(page.text, 'html.parser')
    dk_rows = soup.find_all('tr')
    for dk_row in dk_rows:
        time.sleep(0.2)
        cells = dk_row.find_all('td')
        if len(cells) == 9:
            total_intakes += 1
            this_dict = {'jail': 'prcdf', 'linking': ['recoCsH694PGGUc33']}
            this_dict['link'] = root_url + dk_row.a.get('href')
            try:
                r = requests.get(this_dict['link'], headers=muh_headers)
            except requests.ConnectionError as err:
                damn_it(err)
                continue
            charge_1 = cells[8].string.replace('\xa0', '')
            if 'ã' in charge_1:
                this_dict['charge_1'] = charge_1[0: charge_1.find('ã')]
            else:
                this_dict['charge_1'] = charge_1
            if charge_1 == '18USC132518USC1325 ILLEGAL ENTRY-ALIEN':
                this_dict['charge_1_statute'] = '8 U.S.C. 1325'
                this_dict['charge_1_title'] = 'UNLAWFUL ENTRY'
            this_dict['bk'] = cells[2].string.replace('\xa0', '')
            this_dict['last_verified'] = (
                datetime.utcnow()
                .replace(tzinfo=timezone.utc)
                .strftime('%Y-%m-%d %H:%M')
            )
            this_dict['img_src'] = (
                this_dict['link'].replace('ICUD', 'ICUP').replace('HTM', 'jpg')
            )
            data = []
            soup = BeautifulSoup(r.text, 'html.parser')
            for string in soup.stripped_strings:
                data.append(str(string))
            this_dict['intake_number'] = data[1 + data.index('INTAKE #:')]
            this_dict['DOI'] = f"{data[1 + data.index('INTAKE DATE:')]} {data[1 + data.index('TIME:')]}"
            get_name(data[1 + data.index('Name:')], this_dict)
            this_dict['DOB'] = data[1 + data.index('DOB:')]
            this_dict['intake_age'] = int(data[1 + data.index('AGE:')])
            this_dict['race'] = standardize.prcdf_race(raw_race=data[1 + data.index('RACE:')])
            this_dict['sex'] = data[1 + data.index('SEX:')]
            if data[1 + data.index('OFF DATE:')] != '00/00/0000':
                this_dict['DOO'] = data[1 + data.index('OFF DATE:')]
            this_dict['intake_case_number'] = data[1 + data.index('- Case#:')]
            this_dict['intake_bond_written'] = repr(
                data[1 + data.index('WRITTEN BOND:')]
            ).replace('\xa0', ' ')
            this_dict['intake_bond_cash'] = repr(
                data[1 + data.index('CASH BOND:')]
            ).replace('\xa0', ' ')
            blocks = soup.find_all('table')
            rows = blocks[9].find_all('tr')
            charges = []
            courts = []
            bond_ammounts = []
            for row in rows[1:]:
                cells = row.find_all('td')
                if len(cells) == 3:
                    charge_raw = cells[0].string.strip()
                    court_raw = cells[1].string.strip()
                    if 'ã' in charge_raw:
                        charge = charge_raw[0: charge_raw.find('ã')]
                    else:
                        charge = charge_raw
                    if ', ' in charge:
                        charge = f"\"{charge}\""
                    charges.append(charge)
                    if ' C' in court_raw:
                        courts.append(court_raw[: court_raw.find(' C')])
                    elif court_raw == 'OTHER AGEN':
                        courts.append('OTHER AGENCY')
                    else:
                        courts.append(court_raw)
                    if cells[2].string:
                        amt = '$' + cells[2].string.strip()
                        bond_ammounts.append(amt)
            this_dict['charges'] = ', '.join(charges)
            this_dict['courts'] = ', '.join(courts)
            this_dict['bond_ammounts'] = '\n'.join(bond_ammounts)
            this_dict['recent_text'] = '\n'.join(data[data.index('Name:'):])
            raw_lea = data[1 + data.index('ARRESTING AGENCY:')]
            m = airtab.match(
                'intake_number',
                this_dict['intake_number'],
                view='prcdf',
                fields='recent_text',
            )
            if not m:
                this_dict['LEA'] = standardize.prcdf_lea(raw_lea)
                this_dict['html'] = soup.prettify()
                attachments_array = []
                image_url = {'url': this_dict['img_src']}
                attachments_array.append(image_url)
                this_dict['PHOTO'] = attachments_array
                airtab.insert(this_dict, typecast=True)
                new_intakes += 1
            else:
                update_record(this_dict, soup, m, standardize.prcdf_lea, raw_lea)
    wrap_it_up('prcdf', start_time, new_intakes, total_intakes, log_id, print_table)


def lcdc_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    main_url = ('https://tcsi-roster.azurewebsites.net/Default.aspx?i=26&code=Lee&type=roster')
    r = requests.get(main_url)
    urls = set()
    soup = BeautifulSoup(r.text, 'html.parser')
    for link in soup.find_all('a'):
        url = link.get('href')
        if url[:10] == 'InmateInfo':
            urls.add(url)
    total_intakes = len(urls)
    for url in urls:
        total_intakes += 1
        this_dict = {'jail': 'lcdc', 'linking': ['rec20ZcCFysboY8GP']}
        this_dict['link'] = 'https://tcsi-roster.azurewebsites.net/' + url
        try:
            r = requests.get(this_dict['link'])
        except requests.ConnectionError as err:
            damn_it(err)
            continue
        this_dict['last_verified'] = (datetime.utcnow().replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M'))
        this_dict['bk'] = url[-6:]
        soup = BeautifulSoup(r.text, 'html.parser')
        raw_intake_number = soup.find(id='lblBookingNumber').string
        if len(raw_intake_number) == 1:
            this_dict['intake_number'] = f"{this_dict['bk']}_0{raw_intake_number}"
        else:
            this_dict['intake_number'] = f"{this_dict['bk']}_{raw_intake_number}"
        data = []
        for string in soup.stripped_strings:
            data.append(string)
        text_rn_start = data.index('Booking #') - 1
        this_dict['recent_text'] = '\n'.join(data[text_rn_start: len(data) - 1])
        raw_lea = soup.find(id='lblArrestingAgency').string
        m = airtab.match('intake_number', this_dict['intake_number'], view='lcdc', fields='recent_text')
        if not m:
            this_dict['html'] = soup.prettify()
            if soup.find(id='lblBookingDate').string:
                this_dict['DOI'] = soup.find(id='lblBookingDate').string
            this_dict['LEA'] = standardize.lcdc_lea(raw_lea)
            this_dict['race'] = standardize.lcdc_race(raw_race=soup.find(id='lblRace').string)
            get_name(soup.find(id='lblInmateName').string, this_dict)
            this_dict['DOB'] = soup.find(id='lblBirthdate').string
            this_dict['intake_age'] = int(soup.find(id='lblAge').string)
            if soup.find(id='lblSex').string:
                this_dict['sex'] = soup.find(id='lblSex').string[:1]
            this_dict['glasses'] = soup.find(id='lblGlasses').string
            this_dict['charge_1'] = soup.find(id='lblOffense').string
            this_dict['scheduled_release_date'] = soup.find(id='lblScheduleReleaseDate').string
            airtab.insert(this_dict, typecast=True)
            new_intakes += 1
        else:
            update_record(this_dict, soup, m, standardize.lcdc_lea, raw_lea)
    wrap_it_up('lcdc', start_time, new_intakes, total_intakes, log_id, print_table)


def jcdc_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    url = 'https://www.jonesso.com/roster.php'
    docket_pages = set()
    docket_pages.add(url)
    try:
        r = requests.get(url)
    except requests.ConnectionError as err:
        print('jcdc website is still down')
    else:
        soup = BeautifulSoup(r.text, 'html.parser')
        for x in soup.find_all('a', class_='page_num'):
            page = urllib.parse.urljoin(url, x.get('href'))
            docket_pages.add(page)
        intakes = []
        for page in docket_pages:
            try:
                r = requests.get(page)
            except requests.ConnectionError as err:
                damn_it(err)
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            for x in soup.find_all('a'):
                link = x.get('href')
                if link is not None:
                    if link.startswith('roster_view.php?booking_num'):
                        intakes.append(link)
        total_intakes = len(intakes)
        for x in intakes:
            this_dict = {'jail': 'jcdc', 'linking': ['recuLxs8EEAfHcYfd']}
            this_dict['link'] = f"https://www.jonesso.com/{x}"
            try:
                r = requests.get(this_dict['link'])
            except requests.ConnectionError as err:
                damn_it(err)
                continue
            this_dict['bk'] = x[-5:]
            this_dict['last_verified'] = (
                datetime.utcnow()
                .replace(tzinfo=timezone.utc)
                .strftime('%Y-%m-%d %H:%M')
            )
            soup = BeautifulSoup(r.text, 'html.parser').find(id='cms-content')
            data = []
            for string in soup.stripped_strings:
                data.append(str(string))
            this_dict['recent_text'] = '\n'.join(data[0: len(data) - 1])
            if 'Arresting Agency:' in data:
                raw_lea = data[1 + data.index('Arresting Agency:')]
            else:
                raw_lea = ''
            m = airtab.match('bk', this_dict['bk'], view='jcdc', fields='recent_text')
            if not m:
                this_dict['html'] = soup.prettify()
                get_name(data[data.index('Booking #:') - 1], this_dict)
                if 'Age:' in data:
                    this_dict['intake_age'] = int(data[1 + data.index('Age:')])
                this_dict['sex'] = data[1 + data.index('Gender:')]
                if data[1 + data.index('Race:')] == 'I':
                    this_dict['race'] = 'AI'
                else:
                    this_dict['race'] = data[1 + data.index('Race:')]
                if raw_lea:
                    this_dict['LEA'] = standardize.jcdc_lea(raw_lea)
                this_dict['DOI'] = datetime.strptime(
                    data[1 + data.index('Booking Date:')], '%m-%d-%Y - %I:%M %p').strftime('%m/%d/%Y %I:%M%p')
                c = data[1 + data.index('Charges:')]
                if c.startswith('Note:'):
                    this_dict['charge_1'] = ''
                else:
                    this_dict['charge_1'] = c
                if 'Bond:' in data:
                    this_dict['intake_bond_cash'] = data[1 + data.index('Bond:')]
                this_dict['img_src'] = f"https://www.jonesso.com/templates/jonesso.com/images/inmates/{this_dict['bk']}.jpg"
                image_url = {'url': this_dict['img_src']}
                attachments_array = []
                attachments_array.append(image_url)
                this_dict['PHOTO'] = attachments_array
                if this_dict['img_src'] == 'https://www.jonesso.com/common/images/pna.gif':
                    this_dict['PIXELATED_IMG'] = attachments_array
                airtab.insert(this_dict, typecast=True)
                new_intakes += 1
            else:
                update_record(this_dict, soup, m, standardize.jcdc_lea, raw_lea)
        wrap_it_up('jcdc', start_time, new_intakes, total_intakes, log_id, print_table)


def tcdc_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    url = 'https://www.tunicamssheriff.com/roster.php?grp=10'
    docket_pages = set()
    docket_pages.add(url)
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    for x in soup.find_all('a'):
        y = x.get('href')
        if y.startswith('roster.php?grp='):
            page = urllib.parse.urljoin(url, y)
            docket_pages.add(page)
    intakes = []
    for page in docket_pages:
        r = requests.get(page)
        soup = BeautifulSoup(r.text, 'html.parser')
        for x in soup.find_all('a'):
            link = x.get('href')
            if link:
                if link.startswith('roster_view.php?booking_num'):
                    intakes.append(link)
    total_intakes = len(intakes)
    for x in intakes:
        this_dict = {'jail': 'tcdc', 'linking': ['rec76sKhalCAfQWTT']}
        this_dict['bk'] = x[-10:]
        this_dict['link'] = f"https://www.tunicamssheriff.com/roster_view.php?booking_num={this_dict['bk']}"
        try:
            r = requests.get(this_dict['link'])
        except requests.ConnectionError as err:
            damn_it(err)
            continue
        this_dict['last_verified'] = (
            datetime.utcnow()
            .replace(tzinfo=timezone.utc)
            .strftime('%Y-%m-%d %H:%M')
        )
        soup = BeautifulSoup(r.text, 'html.parser')
        data = []
        for string in soup.stripped_strings:
            data.append(str(string))
        text_rn_start = data.index('Booking #:') - 1
        messy_text_rn = '\n'.join(data[text_rn_start:]).strip()
        this_dict['recent_text'] = messy_text_rn[
            0: messy_text_rn.find('Note: ')
        ].strip()
        try:
            raw_lea = data[1 + data.index('Arresting Agency:')]
        except ValueError:
            raw_lea = ''
        m = airtab.match('bk', this_dict['bk'], view='tcdc')
        if not m:
            this_dict['html'] = soup.prettify()
            get_name(data[data.index('Booking #:') - 1], this_dict)
            if 'Age:' in data:
                this_dict['intake_age'] = int(data[1 + data.index('Age:')])
            this_dict['sex'] = data[1 + data.index('Gender:')]
            if data[1 + data.index('Race:')] != 'Arresting Agency:':
                this_dict['race'] = data[1 + data.index('Race:')]
            if raw_lea:
                this_dict['LEA'] = standardize.tcdc_lea(raw_lea)
            this_dict['DOI'] = datetime.strptime(data[1 + data.index('Booking Date:')],
                                                 '%m-%d-%Y - %I:%M %p').strftime('%m/%d/%Y %H:%M')
            c = data[1 + data.index('Charges:')]
            if c.startswith('Note:') or c.startswith('Bond:'):
                this_dict['charge_1'] = ''
            else:
                this_dict['charge_1'] = c
            if 'Bond:' in data:
                this_dict['intake_bond_cash'] = data[1 + data.index('Bond:')]
            this_dict[
                'img_src'] = f"https://www.tunicamssheriff.com/templates/tunicamssheriff.com/images/inmates/{this_dict['bk']}.jpg"
            image_url = {'url': this_dict['img_src']}
            attachments_array = []
            attachments_array.append(image_url)
            this_dict['PHOTO'] = attachments_array
            airtab.insert(this_dict, typecast=True)
            new_intakes += 1
        else:
            update_record(this_dict, soup, m, standardize.tcdc_lea, raw_lea)
    wrap_it_up('tcdc', start_time, new_intakes, total_intakes, log_id, print_table)


def kcdc_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    docket_pages = set()
    docket_pages.add('roster.php?grp=10')
    r = requests.get('https://www.kempercountysheriff.com/roster.php?grp=10')
    soup = BeautifulSoup(r.text, 'html.parser').find(id='intContentContainer')
    for x in soup.find_all('a'):
        y = x.get('href')
        if y.startswith('roster.php?grp='):
            docket_pages.add(y)
    for page in docket_pages:
        page_url = f"https://www.kempercountysheriff.com/{page}"
        r = requests.get(page_url)
        soup = BeautifulSoup(r.text, 'html.parser').find_all(class_='inmateTable')
        for inmate_block in soup:
            x = inmate_block.find('a').get('href')
            total_intakes += 1
            this_dict = {'jail': 'kcdc', 'linking': ['rec95Usl74WOwfCEj']}
            this_dict['link'] = f"https://www.kempercountysheriff.com/{x}"
            try:
                r = requests.get(this_dict['link'])
            except requests.ConnectionError as err:
                damn_it(err)
                continue
            this_dict['bk'] = x.replace('roster_view.php?booking_num=', '')
            this_dict['last_verified'] = (
                datetime.utcnow()
                .replace(tzinfo=timezone.utc)
                .strftime('%Y-%m-%d %H:%M'))
            soup = BeautifulSoup(r.text, 'html.parser').find(id='intContentContainer')
            data = []
            for string in soup.stripped_strings:
                data.append(str(string))
            messy_text_rn = '\n'.join(data)
            this_dict['recent_text'] = messy_text_rn[0: messy_text_rn.find('Note: ')].strip()
            m = airtab.match('bk', this_dict['bk'], view='kcdc', fields='recent_text')
            if not m:
                this_dict['html'] = soup.prettify()
                get_name(data[0], this_dict)
                if 'Age:' in data:
                    this_dict['intake_age'] = int(data[1 + data.index('Age:')])
                this_dict['sex'] = data[1 + data.index('Gender:')][:1]
                if 'Race:' in data:
                    this_dict['race'] = standardize.kcdc_race(raw_race=data[1 + data.index('Race:')])
                this_dict['DOI'] = datetime.strptime(
                    data[1 + data.index('Booking Date:')], '%m-%d-%Y - %I:%M %p').strftime('%m/%d/%Y %I:%M%p')
                c = data[1 + data.index('Charges:')]
                if c.startswith('Note:'):
                    this_dict['charge_1'] = ''
                else:
                    this_dict['charge_1'] = c
                if 'Bond:' in data:
                    this_dict['intake_bond_cash'] = data[1 + data.index('Bond:')]
                for x in soup.find_all('img'):
                    img_src = x.get('src')
                    if img_src.startswith('templates/kempercountysheriff.com/images/inmates'):
                        this_dict['img_src'] = f"https://www.kempercountysheriff.com/{img_src}"
                try:
                    image_url = {'url': this_dict['img_src']}
                    attachments_array = []
                    attachments_array.append(image_url)
                    this_dict['PHOTO'] = attachments_array
                except KeyError as err:
                    print('no image url')
                airtab.insert(this_dict, typecast=True)
                new_intakes += 1
            else:
                update_record(this_dict, soup, m)
    wrap_it_up('kcdc', start_time, new_intakes, total_intakes, log_id, print_table)


def hcdc_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    try:
        r = requests.get('http://www.co.hinds.ms.us/pgs/apps/inmate/inmate_list.asp')
    except requests.ConnectionError as err:
        damn_it(err)
        return
    soup = BeautifulSoup(r.text, 'html.parser')
    total_pages = int(soup.h3.string.split()[3])
    pages = list(range(1, total_pages + 1))
    for page in pages:
        root_url = 'http://www.co.hinds.ms.us/pgs/apps/inmate/'
        url = f"{root_url}inmate_list.asp?name_sch=Date&SS1=1&search_by_city=&search_by=&ScrollAction=Page+{page}"
        r = requests.get(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) == 7:
                total_intakes += 1
                this_dict = {'jail': 'hcdc', 'linking': ['recHHRRooPmwkCBtP']}
                this_dict['bk'] = row.a.get('href').replace('inmate_detail.asp?ID=', '')
                this_dict['last_verified'] = (
                    datetime.utcnow()
                    .replace(tzinfo=timezone.utc)
                    .strftime('%Y-%m-%d %H:%M')
                )
                m = airtab.match('bk', this_dict['bk'], view='hcdc', fields='recent_text')
                if m:
                    airtab.update(m['id'], this_dict)
                else:
                    this_dict['link'] = f"{root_url}{row.a.get('href')}"
                    try:
                        r = requests.get(this_dict['link'])
                    except requests.ConnectionError as err:
                        damn_it(err)
                        continue
                    this_dict['img_src'] = f"http://www.co.hinds.ms.us/pgs/inmatephotos/{this_dict['bk']}.jpg"
                    this_dict['PHOTO'] = []
                    image_url = {'url': this_dict['img_src']}
                    this_dict['PHOTO'].append(image_url)
                    data = []
                    soup = BeautifulSoup(r.text, 'html.parser')
                    this_dict['html'] = soup.find_all('table')[1].prettify()
                    for string in soup.stripped_strings:
                        data.append(string)
                    try:
                        this_dict['recent_text'] = '\n'.join(data[data.index('Name'): data.index('Disclaimer:')])
                    except ValueError:
                        this_dict['recent_text'] = ''
                    try:
                        get_name(data[1 + data.index('Name')], this_dict)
                        this_dict['intake_address_line_1'] = data[1 + data.index('Address')]
                        this_dict['intake_address_line_2'] = data[2 + data.index('Address')]
                        this_dict['DOB'] = data[1 + data.index('Date of Birth')]
                        this_dict['sex'] = data[1 + data.index('Sex')]
                        if data[1 + data.index('Race')] != 'Height':
                            this_dict['race'] = data[1 + data.index('Race')]
                        raw_doi = data[1 + data.index('Arrest Date')]
                        if raw_doi == date.today().strftime('%m/%d/%Y'):
                            this_dict['DOI'] = datetime.now().strftime('%m/%d/%Y %I:%M%p')
                        else:
                            this_dict['DOI'] = f"{raw_doi} 11:59pm"
                        raw_lea = data[1 + data.index('Arresting Agency')]
                        this_dict['LEA'] = standardize.hcdc_lea(raw_lea)
                        this_dict['charge_1'] = data[1 + data.index('Charge 1')]
                        airtab.insert(this_dict, typecast=True)
                        new_intakes += 1
                    except ValueError as err:
                        print(err, '\n', this_dict['link'])
    wrap_it_up('hcdc', start_time, new_intakes, total_intakes, log_id, print_table)


def ccdc_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    url = 'http://www.claysheriffms.org/roster.php?grp=10'
    docket_pages = set()
    docket_pages.add(url)
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    for x in soup.find_all('a'):
        y = x.get('href')
        if y.startswith('roster.php?grp='):
            page = urllib.parse.urljoin(url, y)
            docket_pages.add(page)
    intakes = []
    for page in docket_pages:
        r = requests.get(page)
        soup = BeautifulSoup(r.text, 'html.parser')
        for x in soup.find_all('a'):
            link = x.get('href')
            if link:
                if link.startswith('roster_view.php?booking_num'):
                    intakes.append(link)
    total_intakes = len(intakes)
    for x in intakes:
        this_dict = {'jail': 'ccdc', 'linking': ['rec7UenhjON284LoO']}
        this_dict['bk'] = x.partition('=')[2]
        this_dict['link'] = f"http://www.claysheriffms.org/roster_view.php?booking_num={this_dict['bk']}"
        try:
            r = requests.get(this_dict['link'])
        except requests.ConnectionError as err:
            damn_it(err)
            continue
        this_dict['last_verified'] = (
            datetime.utcnow()
            .replace(tzinfo=timezone.utc)
            .strftime('%m/%d/%Y %H:%M')
        )
        soup = BeautifulSoup(r.text, 'html.parser').find_all('table')[6]
        data = []
        for string in soup.stripped_strings:
            data.append(string)
        messy_text_rn = '\n'.join(data)
        this_dict['recent_text'] = messy_text_rn[
            0: messy_text_rn.find('Note: ')
        ].strip()
        this_dict['html'] = soup.prettify()
        get_name(data[data.index('Booking #:') - 1], this_dict)
        this_dict['intake_age'] = int(data[1 + data.index('Age:')])
        this_dict['sex'] = data[1 + data.index('Gender:')][:1]
        this_dict['race'] = standardize.ccdc_race(raw_race=data[1 + data.index('Race:')])
        this_dict['DOI'] = datetime.strptime(data[1 + data.index('Booking Date:')],
                                             '%m-%d-%Y - %I:%M %p').strftime('%m/%d/%Y %I:%M%p')
        c = data[1 + data.index('Charges:')]
        if c.startswith('Note:') or c.startswith('Bond:'):
            this_dict['charge_1'] = ''
        else:
            this_dict['charge_1'] = c
        if 'Bond:' in data:
            this_dict['intake_bond_cash'] = data[1 + data.index('Bond:')]
        raw_lea = data[1 + data.index('Arresting Agency:')]
        m = airtab.match('bk', this_dict['bk'], view='ccdc', fields='recent_text')
        if not m:
            this_dict['LEA'] = standardize.ccdc_lea(raw_lea)
            this_dict[
                'img_src'] = f"http://www.claysheriffms.org/templates/claysheriffms.org/images/inmates/{this_dict['bk']}.jpg"
            image_url = {'url': this_dict['img_src']}
            attachments_array = []
            attachments_array.append(image_url)
            this_dict['PHOTO'] = attachments_array
            airtab.insert(this_dict, typecast=True)
            new_intakes += 1
        else:
            update_record(this_dict, soup, m, standardize.ccdc_lea, raw_lea)
    wrap_it_up('ccdc', start_time, new_intakes, total_intakes, log_id, print_table)


def acdc_scraper(log_id, print_table=False):
    start_time = time.time()
    intakes = []
    new_intakes, total_intakes = 0, 0
    docket_pages = ['http://www.adamscosheriff.org/inmate-roster/']
    r = requests.get(docket_pages[0])
    soup = BeautifulSoup(r.text, 'html.parser')
    x = soup.find_all('a', class_='page-numbers')
    page_numbers = range(2, int(x[len(x) - 2].string) + 1)
    for n in page_numbers:
        url = f"http://www.adamscosheriff.org/inmate-roster/page/{n}/"
        docket_pages.append(url)
    for page in docket_pages:
        r = requests.get(page)
        soup = BeautifulSoup(r.text, 'html.parser')
        for x in soup.find_all('p', class_='profile-link'):
            link = x.a.get('href')
            intakes.append(link)
    total_intakes = len(intakes)
    for intake in intakes:
        this_dict = {'jail': 'acdc', 'linking': ['rec9n9Df51OsDc67a']}
        data = []
        this_dict['link'] = intake
        this_dict['last_verified'] = (
            datetime.utcnow()
            .replace(tzinfo=timezone.utc)
            .strftime('%m/%d/%Y %I:%M%p')
        )
        try:
            r = requests.get(intake)
        except requests.ConnectionError as err:
            damn_it(err)
            continue
        soup = BeautifulSoup(r.text, 'html.parser').find('div', class_='blog-content-container')
        for string in soup.stripped_strings:
            data.append(string)
        this_dict['recent_text'] = '\n'.join(data)
        this_dict['html'] = soup.prettify()
        this_dict['bk'] = data[1 + data.index('Booking Number:')]
        if ':' not in data[1 + data.index('Full Name:')]:
            get_name(data[1 + data.index('Full Name:')], this_dict)
        if ':' not in data[1 + data.index('Age:')]:
            this_dict['intake_age'] = int(data[1 + data.index('Age:')])
        if ':' not in data[1 + data.index('Gender:')]:
            this_dict['sex'] = data[1 + data.index('Gender:')]
        if ':' not in data[1 + data.index('Race:')]:
            this_dict['race'] = data[1 + data.index('Race:')]
        raw_doi = data[1 + data.index('Booking Date:')]
        if raw_doi == date.today().strftime('%m/%d/%Y'):
            this_dict['DOI'] = datetime.now().strftime('%m/%d/%Y %I:%M%p')
        else:
            this_dict['DOI'] = f"{raw_doi} 11:59pm"
        charges = data[data.index('Charges:'): data.index('Bond:')]
        if len(charges) > 1:
            this_dict['charges'] = ', '.join(charges[1:])
            this_dict['charge_1'] = charges[1]
        if data[-1] != 'Bond:':
            this_dict['intake_bond_cash'] = data[1 + data.index('Bond:')]
        m = airtab.match('bk', this_dict['bk'], view='acdc')
        if not m:
            if soup.img:
                this_dict['img_src'] = soup.img.get('src')
                image_url = {'url': this_dict['img_src']}
                attachments_array = []
                attachments_array.append(image_url)
                this_dict['PHOTO'] = attachments_array
            else:
                print('problem w/ mugshot')
            airtab.insert(this_dict, typecast=True)
            new_intakes += 1
        else:
            if 'bk' in this_dict:
                update_record(this_dict, soup, m)
    wrap_it_up('acdc', start_time, new_intakes, total_intakes, log_id, print_table)


def jcj_scraper(log_id, print_table=False):
    start_time = time.time()
    new_intakes, total_intakes = 0, 0
    urls = [
        'http://jasperso.com/inmate-roster/',
        'http://jasperso.com/48-hour-release/',
    ]
    for url in urls:
        r = requests.get(url, headers=muh_headers)
        soup = BeautifulSoup(r.text, 'html.parser').find('div', id='primary')
        intakes = soup.find_all('div', class_='col-sm-4 inmate')
        total_intakes += len(intakes)
        for x in intakes:
            this_dict = {'jail': 'jcj', 'linking': ['recuvK2CHQWWr39gc']}
            get_name(x.h1.string.strip(), this_dict)
            this_dict['link'] = url
            data = []
            for string in x.stripped_strings:
                data.append(str(string))
            this_dict['intake_number'] = data[1 + data.index('Arrest #:')]
            this_dict['bk'] = data[1 + data.index('Arrest #:')]
            raw_doi = data[1 + data.index('Arrest Date:')]
            if raw_doi == date.today().strftime('%m/%d/%Y'):
                this_dict['DOI'] = datetime.now().strftime('%m/%d/%Y %I:%M%p')
            else:
                this_dict['DOI'] = f"{raw_doi} 11:59pm"
            if 'Release Date:' in data:
                raw_dor = data[1 + data.index('Release Date:')]
                if raw_dor == date.today().strftime('%m/%d/%Y'):
                    this_dict['DOR'] = datetime.now().strftime('%m/%d/%Y %I:%M%p')
                else:
                    this_dict['DOR'] = f"{raw_dor} 12:01am"
            this_dict['sex'] = data[1 + data.index('Gender:')].strip()[0:1]
            this_dict['race'] = data[1 + data.index('Race:')].strip()[0:1]
            this_dict['intake_age'] = int(data[1 + data.index('Age:')])
            cleaned_charges = []
            charges = data[1 + data.index('Charges:'):]
            for charge in charges:
                if ', ' in charge:
                    cleaned_charge = f"\"{charge}\""
                else:
                    cleaned_charge = charge
                cleaned_charges.append(cleaned_charge)
            this_dict['charges'] = ', '.join(cleaned_charges)
            this_dict['recent_text'] = '\n'.join(data)
            this_dict['html'] = x.prettify()
            this_dict['last_verified'] = (
                datetime.utcnow()
                .replace(tzinfo=timezone.utc)
                .strftime('%Y-%m-%d %H:%M')
            )
            raw_lea = data[1 + data.index('Arrest Agency:')]
            m = airtab.match('bk', this_dict['bk'], view='jcj')
            if not m:
                this_dict['img_src'] = x.find('img').get('src')
                image_url = {'url': this_dict['img_src']}
                attachments_array = []
                attachments_array.append(image_url)
                this_dict['PHOTO'] = attachments_array
                this_dict['LEA'] = standardize.jcj_lea(raw_lea)
                airtab.insert(this_dict, typecast=True)
                new_intakes += 1
            else:
                if this_dict['recent_text'] != m['fields']['recent_text']:
                    this_dict['updated'] = True
                    this_dict['LEA'] = standardize.jcj_lea(raw_lea)
                else:
                    pass
                airtab.update(m['id'], this_dict, typecast=True)
            time.sleep(0.2)
    wrap_it_up('jcj', start_time, new_intakes, total_intakes, log_id, print_table)


def main():
    airtable_log = Airtable('appTKQNP7jG9BVcoo', 'log', os.environ['AIRTABLE_API_KEY'])
    log_entry = airtable_log.insert({'code': 'jail_scraper.py'})
    log_id = log_entry['id']
    fndict = {
        'mcdc': mcdc_scraper,
        'prcdf': prcdf_scraper,
        'lcdc': lcdc_scraper,
        'jcdc': jcdc_scraper,
        'kcdc': kcdc_scraper,
        'tcdc': tcdc_scraper,
        'acdc': acdc_scraper,
        'ccdc': ccdc_scraper,
        'jcj': jcj_scraper,
        'hcdc': hcdc_scraper
    }
    keynames = ['mcdc', 'prcdf', 'lcdc', 'jcdc', 'kcdc', 'tcdc', 'acdc', 'ccdc', 'jcj', 'hcdc']
    jails_str = sys.argv[1]
    if jails_str == 'all':
        jails = keynames
    elif jails_str == 'most':
        jails = keynames[:9]
    else:
        jails = jails_str.split(',')
    if len(sys.argv[1:]) == 2:
        nap_length = int(sys.argv[2])
    else:
        nap_length = 0
    for jail in jails[:-1]:
        fndict[jail.strip()](log_id, print_table=False)
        time.sleep(nap_length)
    fndict[jails[-1]](log_id, print_table=True)


if __name__ == '__main__':
    main()