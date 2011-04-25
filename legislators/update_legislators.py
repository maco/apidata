''' Script for detecting new legislators and getting as much data as possible about them. '''

import csv
import urllib2
import re
import os.path
from collections import defaultdict
import string
from xml.dom import minidom
import lxml.html
from votesmart import votesmart, VotesmartApiError
votesmart.apikey = '496ec1875a7885ec65a4ead99579642c'

STATES = ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
          'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA',
          'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY',
          'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX',
          'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY']
NONSTATES = ['DC', 'PR', 'GU', 'VI', 'AS', 'MP']

class LegislatorTable(object):

    def __init__(self, filename):
        self.csvfile = filename
        self.legislators = {}
        reader = csv.DictReader(open(self.csvfile))
        for line in reader:
            self.legislators[line['bioguide_id']] = line
        self.fieldnames = reader.fieldnames

    def save_to(self, filename):
        writer = csv.DictWriter(open(filename, 'w'), self.fieldnames, 
                                quoting=csv.QUOTE_ALL)
        # write header
        writer.writerow(dict(zip(self.fieldnames, self.fieldnames)))
        for key in sorted(self.legislators.iterkeys()):
            writer.writerow(self.legislators[key])

    def get_legislator(self, **kwargs):
        for leg in self.legislators.itervalues():
            cond = True
            for attname, value in kwargs.iteritems():
                cond = (cond and leg[attname] == value)
            if cond:
                return leg

    def get_legislators(self, **kwargs):
        for leg in self.legislators.itervalues():
            cond = True
            for attname, value in kwargs.iteritems():
                cond = (cond and leg[attname] == value)
            if cond:
                yield leg

    def add_legislator_from_pvs(self, official, bioguide_id):
        person = {}
        # get basic information
        id = person['votesmart_id'] = official.candidateId
        person['firstname'] = official.firstName
        person['middlename'] = official.middleName
        person['lastname'] = official.lastName
        person['name_suffix'] = official.suffix
        person['nickname'] = official.nickName
        person['title'] = official.title[0:3]
        state = person['state'] = official.officeStateId
        district = official.officeDistrictName
        if district == 'Jr':
            district = 'Junior Seat'
        elif district == 'Sr':
            district = 'Senior Seat'
        person['district'] = district
        person['party'] = official.officeParties[0]

        # get information from address
        try:
            offices = votesmart.address.getOffice(id)
            for office in offices:
                if office.state == 'DC':
                    person['congress_office'] = office.street
                    person['phone'] = office.phone1
                    person['fax'] = office.fax1
        except VotesmartApiError:
            pass

        # get information from web address
        webaddr_re = re.compile('.+(house|senate)\.gov.+')
        try:
            webaddrs = votesmart.address.getOfficeWebAddress(id)
            for webaddr in webaddrs:
                if webaddr.webAddressType == 'Website' and webaddr_re.match(webaddr.webAddress):
                    person['website'] = webaddr.webAddress
                elif webaddr.webAddressType == 'Webmail' and webaddr_re.match(webaddr.webAddress):
                    person['webform'] = webaddr.webAddress
        except VotesmartApiError:
            pass

        # get information from bio
        bio = votesmart.candidatebio.getBio(id) 
        if bio.gender:
            person['gender'] = bio.gender[0]
        person['crp_id'] = bio.crpId

        # in_office
        person['in_office'] = '1'

        person['bioguide_id'] = bioguide_id
        self.legislators[bioguide_id] = person


def compare_to(oldfile, newfile, approved_edits=None):
    """
    compare two csv files and allow for copying changes from newfile into 
    oldfile
    """
    old = LegislatorTable(oldfile)
    new = LegislatorTable(newfile)
    if approved_edits is None:
        approved_edits = []

    new_attributes = set()
    changes = defaultdict(set)

    for bio_id, new_leg in new.legislators.iteritems():
        if bio_id not in old.legislators:
            print 'New Legislator:', bio_id
        else:
            this_leg = old.legislators[bio_id]
            for k,v in new_leg.iteritems():
                if v == None:
                    v = ''
                if k not in this_leg:
                    new_attributes.add(k)
                elif this_leg[k] != v:
                    changes[bio_id].add(k)

    # print results
    print 'New Attributes:', ' '.join(new_attributes)

    for attr in new_attributes:
        if attr in approved_edits:
            old.fieldnames.append(attr)
            for leg, new_leg in new.legislators.items():
                old.legislators[leg][attr] = new_leg[attr]

    for leg, changed_keys in changes.iteritems():
        old_leg = old.legislators[leg]
        new_leg = new.legislators[leg]
        print leg, old_leg['firstname'], old_leg['lastname']
        for key in changed_keys:
            print '\t%s: %s -> %s' % (key, old_leg[key], new_leg[key])
            if key in approved_edits:
                old.legislators[leg][key] = new_leg[key]

    old.save_to(oldfile)

def check_bioguide(csvfile):
    table = LegislatorTable(csvfile)

    # get maximum ids 
    max_ids = {}
    for id in sorted(table.legislators.iterkeys()):
        max_ids[id[0]] = id

    # so that if any Q X or Z legislators are elected we'll know
    max_ids.setdefault('Q', 'Q000022')
    max_ids.setdefault('X', 'X000000')
    max_ids.setdefault('Z', 'Z000016')

    # check all urls finding non-tracked bioguide ids
    for letter, max_id in max_ids.iteritems():
        id_num = int(max_id[1:], 10)+1

        while True:
            url = 'http://bioguide.congress.gov/scripts/biodisplay.pl?index=%s%06d' % (letter, id_num)
            page = urllib2.urlopen(url).read()
            if re.search('does not exist', page):
                break
            print '%s%06d' % (letter, id_num),
            results = re.search('<a name="Top">(\w+), (\w+).+</a>', page)
            if results:
                last, first = results.groups()
                print first, last
            else:
                print '--check manually--'
            id_num += 1

def check_sanity(csvfile):
    table = LegislatorTable(csvfile)
    sens = defaultdict(list)
    reps = defaultdict(list)
    dels = defaultdict(list)

    id_fields = ('bioguide_id', 'votesmart_id', 'crp_id', 'fec_id',
                 'govtrack_id')
    unique_ids = defaultdict(set)

    # go through entire list and count active legislators
    for leg in table.get_legislators(in_office='1'):
        if leg['title'] == 'Sen':
            sens[leg['state']].append(leg['district'])
        elif leg['title'] == 'Rep':
            reps[leg['state']].append(leg['district'])
        else:
            dels[leg['state']].append(leg['district']) 

        for f in id_fields:
            id = leg[f]
            if id in unique_ids[f]:
                print 'duplicate values for %s (%s)' % (f, id)
            unique_ids[f].add(id)

    # senators
    for state, districts in sens.iteritems():
        if len(districts) > 2:
            print state, 'has %d senators' % len(districts)
        if 'Junior Seat' not in districts:
            print state, 'has no Junior Senator'
        if 'Senior Seat' not in districts:
            print state, 'has no Senior Senator'

    # representatives
    for state, districts in reps.iteritems():
        num_reps = len(districts)
        districts = sorted(int(x) for x in districts)
        expected = range(1, num_reps+1) if num_reps > 1 else [0]
        if districts != expected:
            print state, 'has districts:', str(districts)

    # delegates
    delstates = dels.keys()
    diffs = set(delstates).symmetric_difference(set(NONSTATES))
    if diffs:
        print 'missing delegates from: %s' % (','.join(diffs))

def _get_xml_value(node, name):
    fc = node.getElementsByTagName(name)[0].firstChild
    return fc.wholeText if fc else ''

def check_senate_xml(csvfile, save=False):
    table = LegislatorTable(csvfile)
    senate_xml_url = 'http://senate.gov/general/contact_information/senators_cfm.xml'
    phone_re = re.compile('\((\d{3})\)\s(\d{3}\-\d{4})')
    senate_xml = urllib2.urlopen(senate_xml_url).read()
    dom = minidom.parseString(senate_xml)
    members = dom.getElementsByTagName('member')
    for member in members:
        bioguide = _get_xml_value(member, 'bioguide_id')
        address = _get_xml_value(member, 'address').split('\n')[0][:-20]
        if address:
            address = string.capwords(address)
        phone = _get_xml_value(member, 'phone')
        if phone:
            phone = '-'.join(phone_re.match(phone).groups())
        webform = _get_xml_value(member, 'email')
        if webform and webform.startswith('mailto'):
            webform = ''
        website = _get_xml_value(member, 'website')

        leg = table.legislators[bioguide]
        if leg['congress_office'] != address:
            print 'Sen %s: changed addr from %s to %s' % (leg['lastname'], leg['congress_office'], address)
            table.legislators[bioguide]['congress_office'] = address
        if leg['phone'] != phone:
            print 'Sen %s: changed phone from %s to %s' % (leg['lastname'], leg['phone'], phone)
            table.legislators[bioguide]['phone'] = phone
        if leg['webform'] != webform:
            print 'Sen %s: changed webform from %s to %s' % (leg['lastname'], leg['webform'], webform)
            table.legislators[bioguide]['webform'] = webform
        if leg['website'] != website:
            print 'Sen %s: changed website from %s to %s' % (leg['lastname'], leg['website'], website)
            table.legislators[bioguide]['website'] = website
    if save:
        table.save_to(csvfile)

def check_missing_data(csvfile):
    table = LegislatorTable(csvfile)
    ignored_fields = ['nickname', 'name_suffix', 'youtube_url', 'twitter_id', 'official_rss', 'middlename', 'senate_class']
    missing = defaultdict(list)
    for leg in table.legislators.itervalues():
        if leg['in_office'] == '1':
            for k,v in leg.iteritems():
                if k not in ignored_fields and not v:
                    missing[k].append(leg['bioguide_id'])
    for field,pols in missing.iteritems():
        polnames = []
        for pol in pols:
            pobj = table.legislators[pol]
            fname = pobj['nickname'] or pobj['firstname']
            polnames.append(fname + ' ' + pobj['lastname'])
        print field, ':', ','.join(polnames)
        print

def get_votesmart_legislators(states):
    for state in states:
        try:
            for leg in votesmart.officials.getByOfficeState(6, state):
                yield leg
        except VotesmartApiError:
            pass

        for leg in votesmart.officials.getByOfficeState(5, state):
            yield leg

def check_votesmart(csvfile, add=False, states=None):
    table = LegislatorTable(csvfile)
    if not states:
        states = STATES
    for leg in get_votesmart_legislators(states):
        if not table.get_legislator(votesmart_id=leg.candidateId):
            print '%s %s (%s)' % (leg.firstName, leg.lastName, leg.candidateId)
            if add:
                bioguide = raw_input('Bioguide ID: ')
                if bioguide:
                    table.add_legislator_from_pvs(leg, bioguide_id=bioguide)
    table.save_to('legislators.csv')

def _check_site(leg, key):
    site = leg[key]
    if site:
        try:
            f = urllib2.urlopen(site)
            if f.geturl() != site:
                print '%s --> %s' % (site, f.geturl())
                leg[key] = f.geturl()
        except urllib2.HTTPError:
            print '404 on %s' % site
        except urllib2.URLError:
            print 'error on %s' % site

def check_urls(csvfile):
    table = LegislatorTable(csvfile)
    for leg in table.legislators.values():
        _check_site(leg, 'website')
    return table

def standardize_file(csvfile):
    DATE_FROM = '%m/%d/%y'
    DATE_TO = '%m/%d/%Y'
    from datetime import datetime
    tbl = LegislatorTable(csvfile)
    for l in tbl.legislators.itervalues():
        date = datetime.strptime(l['birthdate'], DATE_FROM)
        if date.year > 2000:
            date = datetime(date.year-100, date.month, date.day)
        newdate = date.strftime(DATE_TO)
        l['birthdate'] = newdate
    tbl.save_to(csvfile)

# title
# firstname
# middlename
# lastname
# name_suffix
# nickname
# party
# state
# district
# in_office
# gender
# phone
# fax
# website
# webform
# congress_office
# bioguide_id
# votesmart_id
# fec_id
# govtrack_id
# crp_id
# twitter_id
# congresspedia_url
# youtube_url
# official_rss
# senate_class
# birthdate

def scrape_house(csvfile):
    table = LegislatorTable(csvfile)
    base_url = 'http://clerk.house.gov/member_info/mem_contact_info.html?statdis=%s%02d'
    for leg in table.get_legislators(in_office='1', title='Rep'):
        url = base_url % (leg['state'], int(leg['district']))
        data = urllib2.urlopen(url).read()
        doc = lxml.html.fromstring(data)

        # district, addr, city, phone, (optional note about subcommittees)
        pieces = doc.xpath('//div[@id="results"]/p/text()')
        addr = pieces[1]
        addr = addr.strip().replace('HOB', 'House Office Building')
        if addr != leg['congress_office']:
            leg['congress_office'] = addr
            print 'Updated', leg['firstname'], leg['lastname'], 'address'

        # phone
        phone = pieces[3][7:]
        phone = phone.replace('(', '').replace(') ', '-')
        if phone != leg['phone']:
            leg['phone'] = phone
            print 'Updated', leg['firstname'], leg['lastname'], 'phone'

    table.save_to(csvfile)

def check_photos(csvfile, photo_dir):
    table = LegislatorTable(csvfile)
    for leg in table.get_legislators(in_office='1'):
        if not os.path.exists('%s/%s.jpg' % (photo_dir, leg['bioguide_id'])):
            print leg['firstname'], leg['lastname'], leg['bioguide_id']

def main():
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option('-f', '--file', dest='filename', default='legislators.csv',
                      help='file to read legislators from')
    parser.add_option('--bioguide', dest='bioguide', action='store_true', default=False)
    parser.add_option('--sanity', dest='sanity', action='store_true', default=False)
    parser.add_option('--senatexml', dest='senatexml', action='store_true', default=False)
    parser.add_option('--votesmart', dest='votesmart', action='store_true', default=False)
    parser.add_option('--missing', dest='missing', action='store_true', default=False)
    parser.add_option('--checkall', dest='check_all', action='store_true', default=False)
    parser.add_option('--photos', dest='photo_dir', default=None)
    parser.add_option('--reformat', dest='reformat', action='store_true', default=False)
    options, args = parser.parse_args()

    filename = options.filename
    if options.check_all:
        options.bioguide = options.sanity = options.senatexml = options.votesmart = options.missing = True

    def print_header(name):
        print '===================== %s =====================' % name

    if options.bioguide:
        print_header('bioguide')
        check_bioguide(filename)
    if options.sanity:
        print_header('sanity check')
        check_sanity(filename)
    if options.senatexml:
        print_header('senate xml')
        check_senate_xml(filename, True)
    if options.votesmart:
        print_header('votesmart')
        check_votesmart(filename, True)
    if options.missing:
        print_header('missing data')
        check_missing_data(filename)
    if options.photo_dir:
        print_header('checking photos')
        check_photos(filename, options.photo_dir)
    if options.reformat:
        LegislatorTable(filename).save_to(filename)

if __name__=='__main__':
    main()
