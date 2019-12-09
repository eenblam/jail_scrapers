# !/usr/bin/env python3
"""This module does blah blah."""
import glob
import datetime
import os
import time
from bs4 import BeautifulSoup
import pdfkit
import requests
from airtable import Airtable
from documentcloud import DocumentCloud
import send2trash


airtab = Airtable(os.environ['jail_scrapers_db'],
                  'intakes', os.environ['AIRTABLE_API_KEY'])

airtab_log = Airtable(os.environ['log_db'], 'log', os.environ['AIRTABLE_API_KEY'])

dc = DocumentCloud(os.environ['DOCUMENT_CLOUD_USERNAME'], os.environ['DOCUMENT_CLOUD_PW'])

jails_lst = [['mcdc', 'intake_number'],
             ['prcdf', 'intake_number'],
             ['lcdc', 'intake_number'],
             ['jcadc', 'intake_number'],
             ['tcdc', 'bk'],
             ['kcdc', 'bk'],
             ['ccdc', 'bk'],
             ['acdc', 'bk'],
             ['hcdc', 'bk']]

muh_headers = {'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'}


def wrap_it_up(t0, new, total=None, function=None):
    this_dict = {'module': 'jail_scrapers/pdf_stuff.py'}
    this_dict['function'] = function
    this_dict['duration'] = round(time.time() - t0, 2)
    this_dict['total'] = total
    this_dict['new'] = new
    airtab_log.insert(this_dict, typecast=True)


def web_to_pdf():
    t0, i = time.time(), 0
    records = airtab.get_all(view='needs pdf')
    i = len(records)
    for record in records:
        url = record['fields']['link']
        jail = record['fields']['jail']
        os.chdir(f"{os.getenv('HOME')}/code/jail_scrapers/output/{jail}")
        if jail in {'mcdc', 'prcdf', 'lcdc', 'jcadc'}:
            fn = f"{record['fields']['intake_number']}.pdf"
        else:
            fn = f"{record['fields']['bk']}.pdf"
        options = {
            'quiet': '',
            'footer-right': time.strftime('%c'),
            'footer-left': url,
            'javascript-delay': 5000}
        if jail == 'lcdc':
            options['zoom'] = '.75'
            options['viewport-size'] = '1000x1400'
            options['footer-font-size'] = 9
        else:
            options['footer-font-size'] = 10
        if jail in {'mcdc', 'prcdf'}:
            r = requests.get(url, headers=muh_headers)
            data = []
            soup = BeautifulSoup(r.text, 'html.parser')
            for string in soup.stripped_strings:
                data.append(str(string))
            if record['fields']['intake_number'] == data[1 + data.index('INTAKE #:')]:
                pdfkit.from_url(url, fn, options)
            else:
                print('the intake number does not match!')
        else:
            pdfkit.from_url(url, fn, options)
    wrap_it_up(t0, i, function='web_to_pdf')


def pdf_to_dc():
    t0, i = time.time(), 0
    for jail in jails_lst:
        os.chdir(f"{os.getenv('HOME')}/code/jail_scrapers/output/{jail[0]}")
        for fn in glob.glob('*.pdf'):
            obj = dc.documents.upload(fn, access="public")
            obj = dc.documents.get(obj.id)
            while obj.access != "public":
                time.sleep(7)
                obj = dc.documents.get(obj.id)
            this_dict = {"jail": jail[0]}
            obj.data = this_dict
            obj.put()
            this_dict["dc_id"] = obj.id
            this_dict["dc_title"] = obj.title
            this_dict["dc_access"] = obj.access
            this_dict["dc_pages"] = obj.pages
            full_text = obj.full_text.decode("utf-8")
            this_dict["dc_full_text"] = os.linesep.join(
                [s for s in full_text.splitlines() if s]
            )
            record = airtab.match(
                jail[1], this_dict["dc_title"], view=jail[0])
            airtab.update(record["id"], this_dict)
            send2trash.send2trash(fn)
            i += 1
            time.sleep(3)
    wrap_it_up(t0, i, function='pdf_to_dc')


def get_dor_if_possible():
    t0, i = time.time(), 0
    records = airtab.get_all(view="needs DOR")
    total = len(records)
    for record in records:
        this_dict = {}
        r = requests.get(record["fields"]["link"])
        soup = BeautifulSoup(r.text, "html.parser")
        data = []
        for string in soup.stripped_strings:
            data.append(str(string))
        if "Release Date:" in data:
            os.chdir(
                f"{os.getenv('HOME')}/code/jail_scrapers/output/{record['fields']['jail']}/updated")
            options = {
                "quiet": "",
                "footer-font-size": 10,
                "footer-left": record["fields"]["link"],
                "footer-right": time.strftime('%c'),
            }
            fn = f"{record['fields']['bk']} (final).pdf"
            pdfkit.from_url(record["fields"]["link"], fn, options=options)
            this_dict["DOR"] = datetime.datetime.strptime(
                data[1 + data.index("Release Date:")], "%m-%d-%Y - %I:%M %p"
            ).strftime('%m/%d/%Y %H:%M')
            airtab.update(record["id"], this_dict)
            i += 1
    wrap_it_up(t0, i, total, function='get_dor_if_possible')


def main():
    web_to_pdf()
    pdf_to_dc()
    get_dor_if_possible()


if __name__ == "__main__":
    main()