#### Imports #### 
import sys
import os.path
import argparse
import datetime
import json
import xml.etree.ElementTree as ET
import secrets
import getpass
from decimal import Decimal

# Non-standard Dependencies
from configparser_crypt import ConfigParserCrypt
import plaid # Lots of these because of the way the plaid module works... or I just can't figure out how it's intended to work
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from ofxtools.models import *
from ofxtools.header import make_header
from ofxtools.utils import UTC


#######################
#### Configuration ####
#######################
# Parse arguments
parser = argparse.ArgumentParser()
parser.add_argument("-u", "--updateconf", action="store_true", help="Update previously stored API and other configuration items, then exit.")
parser.add_argument("-l", "--linkaccount", action="store_true", help="Link an additional account. You'll be prompted interactively for the link account name.")
parser.add_argument("-s", "--showaccounts", action="store_true", help="Just enumerate the linked accounts in config then exit. Access tokens will NOT be displayed.")
parser.add_argument("-a", "--account", help="Use this if you only want to work with a specific linked account instead of all saved accounts. Use the label you specified for this account when first set up.")
args = parser.parse_args()

# Most of this is managed in an encrypted config file stored wherever the script is run.
conffile = 'plaid2qfx.conf'
conf = ConfigParserCrypt()
if os.path.exists(conffile):
    try:
        hexkey = getpass.getpass("Your configuration key: ")
        conf.aes_key = bytes.fromhex(hexkey)
        conf.read_encrypted(conffile)
    except:
        print("I was unable to open the configuration file. You may not have provided the right key. Exiting.")
        sys.exit(404)
else:
    # Generate a new encrypted config key
    print("Looks like you don't have a configuration file yet, so I will create one. It will be encrypted using the following randomly generated key that you are responsible for protecting:")
    conf.generate_key()
    print(conf.aes_key.hex())
    _ = input("Press enter once you have saved this key.")
    
    # Generate the basic Plaid API and user config
    conf.add_section('PLAID')
    conf['PLAID']['client_id'] = input("Please provide your Plaid API client_id: ")
    conf['PLAID']['client_s'] = getpass.getpass('Please provide your client API Secret: ')
    conf['PLAID']['client_user_id'] = secrets.token_hex(16) # This is intended for identifying multiple users of a production application, not really useful for a single-user script implementation, so randomly assigned one.
    
    # Set up some location variables
    homedir = os.path.expanduser("~")
    conf['PLAID']['ofxloc'] = input("Where would you like output files stored? [" + homedir + "]: ") or homedir
    while not os.path.isdir(conf['PLAID']['ofxloc']):
        conf['PLAID']['ofxloc'] = input("That path doesn't seem to be a directory, please try again (" + homedir + "): ")

    # Write the initial conffile
    with open(conffile, 'wb') as file_handle:
        conf.write_encrypted(file_handle)

# And some static config things...
client_name = "plaid2qfx_python"
defaulttime = datetime.time(12, 0, 0, tzinfo=UTC) # Used when transactions only have date because OFX requires full datetime


##################################
#### Setup and Initialization ####
##################################
# Start initiation some Plaid endpoints
plaid_api_configuration = plaid.Configuration(
    host=plaid.Environment.Development, # Available environments are 'Production', 'Development', and 'Sandbox'
    api_key={
        'clientId': conf['PLAID']['client_id'],
        'secret': conf['PLAID']['client_s'],
    }
)
api_client = plaid.ApiClient(plaid_api_configuration)
client = plaid_api.PlaidApi(api_client)

# DEBUG STUFF TO REMOVE
#args.updateconf = True
#args.linkaccount = True
#args.showaccounts = True
#args.account = "DCCU"
#conf['DCCU']['cursor'] = ""


##############
#### MAIN ####
##############
def main():
    
    # If updateconf was specified in arguments...
    if args.updateconf:
        update_config(conffile)
    
    # If we don't have any accounts defined, gotta link one. The first conf section is Plaid API stuff. We need at least two.
    elif len(conf.sections()) < 2:
        print("Doesn't look like we have any accounts defined yet. Let's set one up.")
        link_name = link_account()
        print("Thank you. It looks like ", link_name, " was added successfully.")
        
        # Download transactions for the newly linked account?
        reply = input("Would you like to go ahead and export transactions for this account? You could say no, and re-run the script with the --linkaccount option to add more first. (y/n) ")
        if reply in ('y', 'yes', 'Y', 'Yes', 'YES'):
            process_item(link_name)

    # If linkaccount was specified in arguments...
    elif args.linkaccount:
        print("Lets add a new linked account.")
        link_name = link_account()
        print("Thank you. It looks like ", link_name, " was added successfully.")
        
        # Download transactions for the newly linked account?
        reply = input("Would you like to go ahead and export transactions for just this account? (y/n) ")
        if reply in ('y', 'yes', 'Y', 'Yes', 'YES'):
            process_item(link_name)

    # If showaccounts was specified in arguments...
    elif args.showaccounts:
        showaccounts()

    # If a specific account was targeted in arguments...
    elif args.account:
        if args.account in conf.sections():
            link_name = args.account
            process_item(link_name)
        else: 
            print("I could not find the specified account. Exiting.")
            sys.exit(302)

    # Otherwise, start processing all accounts
    else:
        for section in conf.sections():
            if (section == 'PLAID'):
                continue
            process_item(section)

    sys.exit()


######################
#### Process Item ####
# This how we string together the typical actions needed each time a 
# certain plaid item (or "Linked Account") is processed.
######################
def process_item(link_name):
    (accounts, ins_id) = get_accounts(link_name, True)
    (added, modified, removed) = get_transactions(link_name)
    total = len(added) + len(modified) + len(removed)
    if total > 0:
        process_transactions(link_name, accounts, added, modified, removed)


#######################
#### Update Config ####
#######################
def update_config(conffile):

    homedir = os.path.expanduser("~")

    # Probably not needed, but just in cases someone wants to set up config before running the main parts of the script...
    if not os.path.exists(conffile):
        # Generate a new encrypted config key
        print("Looks like you don't have a configuration file yet, so I will create one. It will be encrypted using the following randomly generated key that you are responsible for protecting:")
        conf.generate_key()
        print(conf.aes_key.hex())
        _ = input("Press enter once you have saved this key.")
    
        # Generate the basic Plaid API and user config
        conf.add_section('PLAID')
        conf['PLAID']['client_id'] = input("Please provide your Plaid API client_id: ")
        conf['PLAID']['client_s'] = getpass.getpass('Please provide your client API Secret: ')
        conf['PLAID']['client_user_id'] = secrets.token_hex(16)
        
        # Set up some location variables
        conf['PLAID']['ofxloc'] = input("Where would you like output files stored? [" + homedir + "]: ") or homedir
        while not os.path.isdir(conf['PLAID']['ofxloc']):
            conf['PLAID']['ofxloc'] = input("That path doesn't seem to be a directory, please try again (" + homedir + "): ")
    
    else:
        reply = input("Would you like to get a new encryption key? [n] ") or "n"
        if reply in ('y', 'yes', 'Y', 'Yes', 'YES'):
            conf.generate_key()
            print(conf.aes_key.hex())
            _ = input("Press enter once you have saved this key.")            
        
        if 'PLAID' in conf.sections():
            if 'ofxloc' in conf['PLAID']:
                conf['PLAID']['ofxloc'] = input("Export location: [" + conf['PLAID']['ofxloc'] + "]") or conf['PLAID']['ofxloc']
                while not os.path.isdir(conf['PLAID']['ofxloc']):
                    conf['PLAID']['ofxloc'] = input("That path doesn't seem to be a directory, please try again (" + homedir + "): ")    
            else:
                conf['PLAID']['ofxloc'] = input("Where would you like output files stored? [" + homedir + "]: ") or homedir
                while not os.path.isdir(conf['PLAID']['ofxloc']):
                    conf['PLAID']['ofxloc'] = input("That path doesn't seem to be a directory, please try again (" + homedir + "): ")
        ##### CONTINUE WRITING THIS LATER
    
    # Finally, write the config
    with open(conffile, 'wb') as file_handle:
        conf.write_encrypted(file_handle)
    print("Configuration updated.")



######################
#### New Accounts ####
######################
def link_account():
    # Get and validate the new account label
    if args.account:
        link_name = args.account
    else:
        link_name = input("For the purposes of this script, what label would you like to give this linked account? ")
    if link_name in conf.sections():
        print("ERROR - The name of the new account has already been used. Please try again with a unique name. Unfortunately I'm not smart enough yet to update existing accounts.")
        sys.exit(1)
    
    # Create a link_token for the given user
    request = LinkTokenCreateRequest(
            products=[Products('transactions')],
            client_name=client_name,
            country_codes=[CountryCode('US')],
            language='en',
            user=LinkTokenCreateRequestUser(
                client_user_id=conf['PLAID']['client_user_id']
            )
        )
    response = client.link_token_create(request)

    # Generate auth page with that link token
    page_path = generate_auth_page(response['link_token'])

    # Get the resulting public ID from the user
    print("\nThe next step is to open ", end='')
    print("\033[01m \033[04m {}\033[00m" .format(page_path), end='')
    print(" in your web browser.")
    public_token = input("Enter your public_token from the auth page: ")

    # Get our access token and item_id
    request = ItemPublicTokenExchangeRequest(
      public_token=public_token
    )
    response = client.item_public_token_exchange(request)

    # Store all of this in our config file
    conf.add_section(link_name)
    conf[link_name]['access_token'] = response['access_token']
    conf[link_name]['item_id'] = response['item_id'] 
    
    # Gather some account info
    (accounts, ins_id) = get_accounts(link_name, True)
    
    # And we will need the routing number for this institution later.
    request2 = InstitutionsGetByIdRequest(
        institution_id=ins_id,
        country_codes=[CountryCode('US')]
    )
    response2 = client.institutions_get_by_id(request2)
    if len(response2['institution']['routing_numbers']) > 1:
        print("Known routing numbers for this institution:")
        for rn in response2['institution']['routing_numbers']:
            print("   " + rn)
        rn = input("What routing number would you like to use with " + link_name + "? This isn't critical, just used as an identifier in OFX, but instead of me randomly picking, figure I'll give you a chance. ")
    else:
        rn = response2['institution']['routing_numbers'][0]
    
    # And for QFX, we need Intuit's institution IDs
    print("And for QFX, Quicken requires a BID number identifying the bank as a participant of Web Connect. You can look up your bank and find their BID here: https://ofx-prod-filist.intuit.com/qm2400/data/fidir.txt  If you split it into columns in Excel it's easier to read. Search for your Bank, ensure they offer WEB-CONNECT (column J), and enter the BID found in column C.")
    bid = input("BID: ")

        
    conf[link_name]['ins_id'] = ins_id
    conf[link_name]['routing_number'] = rn
    conf[link_name]['bid'] = bid
    with open(conffile, 'wb') as file_handle:
        conf.write_encrypted(file_handle)

    # Clean up
    os.remove(page_path)
    return(link_name)

def generate_auth_page(link_token):
    authfile = 'auth.html'
    html = """<html>
    <body>
        <h1>Plaid2QFX_Python</h1>
        <p>Okay look, Plaid is really intended to be used as part of a fancy web application. I'm not that smart. But the safest way to do the institution login stuff is to let Plaid do it, NOT for me to try to script anything different. Click the button below to kick off the Plaid institution login and linking flow. Nothing in the resulting interface is available to this script - your password and how it is protected is between you and Plaid. </p>
        <button id='linkButton'>Start Linking My Bank</button>
        <p>The results of the process will appear below. You will need to copy the public_token value back into the script.</p>
        <p id="results"></p>
        <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
        <script>
            var linkHandler = Plaid.create({
                token: '""" + link_token + """',
                onLoad: function() {
                    // The Link module finished loading.
                },
                onSuccess: function(public_token, metadata) {
                    document.getElementById("results").innerHTML = "public_token: " + public_token;
                },
                onExit: function(err, metadata) {
                    // The user exited the Link flow.
                    if (err != null) {
                        // The user encountered a Plaid API error prior to exiting.
                    }
                }
            });
            // Trigger the standard institution select view
            document.getElementById('linkButton').onclick = function() {
                linkHandler.open();
            };
        </script>
    </body>
</html>"""
    realpath = ''
    with open(authfile, "w") as af:
        af.write(html)
        realpath = os.path.realpath(af.name)
    return(realpath)


#######################################
#### Getting Accounts from an Item ####
#######################################
def get_accounts(link_name, print_it):
    request = AccountsGetRequest(
        access_token=conf[link_name]['access_token']
    )
    response = client.accounts_get(request)
    accounts = response['accounts']
    
    if print_it:
        print("-----------------------")
        print("Accounts:")
        for item in accounts:
            text = "  " + str(item['name']) + " x" + str(item['mask'])
            text = text.ljust(32)
            print(text + ": " + item['account_id'])
        print("-----------------------")
    return(accounts, response['item']['institution_id'])


##############################
#### Getting Transactions ####
##############################
def get_transactions(link_name):
    
    # Blank for the first time
    if not 'cursor' in conf[link_name]:
        cursor = ''
    else:
        cursor = conf[link_name]['cursor']
    
    # Initialize
    added = []
    modified = []
    removed = []
    has_more = True

    # Iterate through pages of new transactions
    print("Loading transactions...")
    while has_more:
        request = TransactionsSyncRequest(
            access_token=conf[link_name]['access_token'],
            cursor=cursor,
        )
        response = client.transactions_sync(request)

        # Add this page of results
        added.extend(response['added'])
        modified.extend(response['modified'])
        removed.extend(response['removed'])

        # Update Cursor
        has_more = response['has_more']
        cursor = response['next_cursor']
        
        # Print number of transactions so far
        total = len(added) + len(modified) + len(removed)
        if has_more:
            print("Loaded " + str(total) + "... ", end='\r')
        else:
            print("Finished downloading " + str(total) + " transactions.")

    # Store updated cursor
    conf[link_name]['cursor'] = cursor
    with open(conffile, 'wb') as file_handle:
        conf.write_encrypted(file_handle)
    
    # Return retrieved data
    return(added, modified, removed)


#################################
#### Processing Transactions ####
#################################
def process_transactions(link_name, accounts, added, modified, removed):
    
    # Modified and Removed Transactions not yet supported
    if len(modified) > 0:
        print("WARNING!! There are modified transactions that I don't know how (or even if) OFX handles. These will not be included in your export.")
    if len(removed) > 0:
        print("WARNING!! There are removed transactions that I don't know how (or even if) OFX handles. These will not be included in your export.")

    # Do I have anything else to process?
    if len(added) < 1: 
        print("No transactions to process for linked account " + link_name + ".")
        return
    else:
        print("Processing " + str(len(added)) + " transactions for linked account " + link_name + ".")
    
    # Initialize Accounts structure we will use to organize unsorted transactions across multiple accounts
    objaccounts = {}

    # What was the latest transactions update for this item / link_name?
    request = ItemGetRequest(access_token=conf[link_name]['access_token'])
    response = client.item_get(request)
    dtasof = response['status']['transactions']['last_successful_update']
    dtstart = dtasof
    dtend = dtasof
    if conf[link_name]['ins_id'] != response['item']['institution_id']:
        print("WARNING - The instituion ID Plaid sent in response to my /item/get request does not match the ID stored in this scripts configuration, and I can't think of any good reasons for that to happen. I'll update my configuration to match what Plaid sent, but something may be seriously screwed up.")
        conf[link_name]['ins_id'] = response['item']['institution_id']
    print("By the way, transactions for linked account " + link_name + " were last updated in Plaid on " + dtasof.strftime("%a, %B %d, %Y %I:%M%p %Z") + ".")

    # First we will initialize ofx entries in this item's accounts object. This is just to organize our data for export.
    for account in accounts:
        
        # What type of account is it?
        # NOTE - OFX only accepts 22-character account IDs, and Plaid's IDs far exceed that length, so I'm just truncating. Probably should add some error handling to check for duplicate entries. One day.
        accttype=parse_accttype(account['type'].to_str(), account['subtype'].to_str())
        if accttype == "CREDITCARD":
            acctfrom = CCACCTFROM(acctid=account['account_id'][:22])
        else:
            acctfrom = BANKACCTFROM(bankid=conf[link_name]['routing_number'],
                                    acctid=account['account_id'][:22],
                                    accttype=accttype)
        
        # Add some details
        ledgerbal = LEDGERBAL(balamt=Decimal(str(account['balances']['current'])), 
                             dtasof=dtasof)
        if account['balances']['available']:
            availbal = AVAILBAL(balamt=Decimal(str(account['balances']['available'])),
                                dtasof=dtasof)
        else:
            availbal = AVAILBAL(balamt=Decimal('0'),
                                dtasof=dtasof)

        # Store to our dictionary
        objaccounts[account['account_id']] = account
        objaccounts[account['account_id']]['ledgerbal'] = ledgerbal
        objaccounts[account['account_id']]['availbal'] = availbal
        objaccounts[account['account_id']]['accttype'] = accttype
        objaccounts[account['account_id']]['acctfrom'] = acctfrom
        objaccounts[account['account_id']]['stmttrns'] = []
        

    # Focus on added transactions
    for trans in added:
        
        # Make sure this transaction maps to a known account
        if not trans['account_id'] in objaccounts:
            print("WARNING!!! Skipping transaction for unknown account id: " + trans['account_id'])
            continue

        # Dates are a PITA, and I don't know why.
        dtposted = trans['authorized_datetime'] or trans['authorized_date'] or trans['datetime'] or trans['date']
        if not isinstance(dtposted, datetime.datetime):
            dtposted = datetime.datetime.combine(dtposted, defaulttime) 
        if dtposted < dtstart:
            dtstart = dtposted

        # Currency - OFX specifies currency at the statement level, Plaid provides it per transaction. 
        # Assume the first transaction's currency will match the rest, and watch for deviation.
        if 'iso_currency_code' in trans and trans['iso_currency_code']: # the property exists and it is not none
            if not 'curdef' in objaccounts[trans['account_id']]: # Set the first one.
                objaccounts[trans['account_id']]['curdef'] = trans['iso_currency_code']
            if objaccounts[trans['account_id']]['curdef'] != trans['iso_currency_code']: # Make sure the rest match
                print("WARNING!!! The currency code for this transaction doesn't match others! First currency found for this account: " +  objaccounts[trans['account_id']]['curdef'] + ". Currency code for transaction id " + trans['transaction_id'] + " is: " + trans['iso_currency_code'])
                # Don't do anything but warn though...

        # A little more info before we write a transaction entry.
        trntype = parse_transcat(trans['category'])

        # Now write the properly formatted transaction entry. 
        if trans['check_number']:
            objaccounts[trans['account_id']]['stmttrns'].append(STMTTRN(trntype=trntype,
                                                                  dtposted=dtposted,
                                                                  trnamt=Decimal(str(trans['amount']))*-1,
                                                                  fitid=trans['transaction_id'],
                                                                  checknum=trans['check_number'], 
                                                                  name=trans['merchant_name']))
        else:
            objaccounts[trans['account_id']]['stmttrns'].append(STMTTRN(trntype=trntype,
                                                                  dtposted=dtposted,
                                                                  trnamt=Decimal(str(trans['amount']))*-1,
                                                                  fitid=trans['transaction_id'],
                                                                  name=trans['merchant_name'],
                                                                  memo=trans['name']))

    # Now generate the banktranlist for each account
    for accountid in objaccounts:
        
        # Did we get a currency code? Why I overengineer for some potential errors and just pray for the rest... 
        if not 'curdef' in objaccounts[accountid]:
            print("WARNING - No currency code was found in transactions for account " + accountid + ". Assuming USD.")
            objaccounts[accountid]['curdef'] = "USD"

        # BANKTRANLIST
        objaccounts[accountid]['banktranlist'] = BANKTRANLIST(dtstart=dtstart, dtend=dtend, *objaccounts[accountid]['stmttrns'])

    # To join multiple accounts into one file we have to collect stmttrnrs sections (and the CC equivalent)
    creditcardmsgsrs_list = []
    stmttrnrs_list = []
    for accountid in objaccounts:
        if objaccounts[accountid]['accttype'] == "CREDITCARD":
            ccstmtrs = CCSTMTRS(curdef=objaccounts[accountid]['curdef'],
                                ccacctfrom=objaccounts[accountid]['acctfrom'],
                                banktranlist=objaccounts[accountid]['banktranlist'],
                                ledgerbal=objaccounts[accountid]['ledgerbal'],
                                availbal=objaccounts[accountid]['availbal'])
            status = STATUS(code=0, severity='INFO')
            creditcardmsgsrs_list.append(CCSTMTTRNRS(trnuid='0', status=status, ccstmtrs=ccstmtrs))

        else:
            stmtrs = STMTRS(curdef=objaccounts[accountid]['curdef'],
                                bankacctfrom=objaccounts[accountid]['acctfrom'],
                                banktranlist=objaccounts[accountid]['banktranlist'],
                                ledgerbal=objaccounts[accountid]['ledgerbal'],
                                availbal=objaccounts[accountid]['availbal'])  
            status = STATUS(code=0, severity='INFO')
            stmttrnrs_list.append(STMTTRNRS(trnuid='0', status=status, stmtrs=stmtrs))
    
    # More wrapping and formatting
    fi = FI(org=link_name, fid=conf[link_name]['routing_number'])
    sonrs = SONRS(status=status,
                dtserver=dtasof, # because I don't really care
                language="ENG",
                fi=fi)
    signonmsgs = SIGNONMSGSRSV1(sonrs=sonrs)

    # Final putting together of the OFX body, depending on what account types were present
    if len(creditcardmsgsrs_list) > 0 and len(stmttrnrs_list) > 0:
        creditcardmsgsrs = CREDITCARDMSGSRSV1(*creditcardmsgsrs_list)
        bankmsgsrs = BANKMSGSRSV1(*stmttrnrs_list)
        ofx = OFX(signonmsgsrsv1=signonmsgs, creditcardmsgsrsv1=creditcardmsgsrs, bankmsgsrsv1=bankmsgsrs)
    elif len(creditcardmsgsrs_list) > 0:
        creditcardmsgsrs = CREDITCARDMSGSRSV1(*creditcardmsgsrs_list)
        ofx = OFX(signonmsgsrsv1=signonmsgs, creditcardmsgsrsv1=creditcardmsgsrs)
    elif len(stmttrnrs_list) > 0:
        bankmsgsrs = BANKMSGSRSV1(*stmttrnrs_list)
        ofx = OFX(signonmsgsrsv1=signonmsgs, bankmsgsrsv1=bankmsgsrs)
    else:
        print("ERROR!!! It seems there were transactions to process initially, but I must have missed something, because there are no CCSTMTTRNRS or STMTTRNRS sections to process. Exiting.")
        sys.exit(129)

    # Add the Quicken proprietary tag and export. Woot!!!
    root = ofx.to_etree()
    tag = ET.SubElement(root[0][0], 'INTU.BID')
    tag.text = conf[link_name]['bid']
    ET.indent(root)
    text = ET.tostring(root, encoding='unicode')
    header = str(make_header(version=102))
    text = header+text
    filename = link_name + "_" + f"{datetime.datetime.now():%Y-%m-%d_%H%M%S%f}" + ".qfx"
    fullpath = os.path.join(conf['PLAID']['ofxloc'], filename)
    with open(fullpath, 'w') as file_handle:
        file_handle.write(text)
        print("Successfully exported transactions to: " + fullpath)

    return

def parse_accttype(typ, subtype):
    # There are a lot of account types you might see in Plaid. https://plaid.com/docs/api/accounts/#account-type-schema
    # But only a few are accepted per OFX standard 1.0.2: CHECKING, SAVINGS, MONEYMRKT, CREDITLINE, and though under a different heading type, we'll also return CREDITCARD.
    # I don't really understand the implications of these mappings, and frankly, I only care about this script for my basic checking and savings accounts. Sorry.
    if typ == "depository":
        if subtype == "savings" or subtype == "hsa" or subtype == "cd":
            return("SAVINGS")
        elif subtype == "money market":
            return("MONEYMRKT")
        else:
            return("CHECKING")
    elif typ == "credit":
        return("CREDITCARD")
    elif typ == "loan":
        return("CREDITLINE")
    elif typ == "investment":
        return("MONEYMRKT")
    else:
        return("CHECKING")

def parse_transcat(category):
    # There are a lot of categories used by Plaid. Access the list by running categories = client.categories_get({}).
    # These have to be mapped to a handful of OFX specified categories found in ofxtools TRNTYPES.
    # Again, best effort is more than enough for now. 
    try:
        if category[0] == "Bank Fees":
            trntype = "FEE"
        elif category[0] == "Cash Advance":
            trntype = "CASH"
        elif category[0] == "Interest":
            trntype = "INT"
        elif category[0] == "Payment":
            trntype = "PAYMENT"
        elif category[0] == "Tax":
            if len(category) > 1 and category[1] == "Payment":
                trntype = "DEBIT"
            elif len(category) > 1 and category[1] == "Refund":
                trntype = "CREDIT"
            else:
                trntype = "CREDIT"
        elif category[0] == "Transfer":
            if len(category) > 1 and category[1] == "Check":
                trntype = "CHECK"
            elif len(category) > 2 and category[2] == "Check":
                trntype = "CHECK"
            elif len(category) > 1 and category[1] == "Deposit":
                trntype = "DEP"
            elif len(category) > 2 and category[2] == "ATM":
                trntype = "ATM"
            else:
                trntype = "XFER"
        else: 
            trntype = "DEBIT" # Use this for the vast majority of categories
    
    except:
        print("WARNING!!! Category parsing failed on category " + category + " . Attempting to continue... but could get ugly.")
        return("CAT_ERROR")
    
    return(trntype)


###################################
#### Enumerate Linked Accounts ####
###################################
def showaccounts():
    for section in conf.sections():
        if (section == 'PLAID'):
            continue
        print("\nLinked Account --- " + section)
        for key in conf[section]:
            if key=="access_token" or key=="accounts":
                continue
            print("    Key: " + key.ljust(15), end='  ')
            print("Value: " + conf[section][key])


##############################################
#### Last but not least... execute main() ####
##############################################
if __name__ == "__main__":
    main()
