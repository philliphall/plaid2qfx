#### Imports #### 
import sys
import os.path
import argparse
import json
import secrets
import getpass
from configparser_crypt import ConfigParserCrypt
import plaid # Lots of these because of the way the plaid module works...
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode

#### Configuration ####
# Most of this is from the following config file
file = 'plaid2qfx.conf'
conf = ConfigParserCrypt()
if os.path.exists(file):
    try:
        hexkey = getpass.getpass("Your configuration key: ")
        conf.aes_key = bytes.fromhex(hexkey)
        conf.read_encrypted(file)
    except:
        print("I was unable to open the file. You may not have provided the right key. Exiting.")
        sys.exit(404)
else:
    # Generate a new encrypted config key
    conf.generate_key()
    print("Looks like you don't have a config file yet, so I will create one. It will be encrypted using the following randomly generated key that you are responsible for protecting:")
    print(conf.aes_key.hex())
    input("Press enter once you have saved this key.")
    
    # Generate the basic Plaid API and user config
    conf.add_section('PLAID')
    conf['PLAID']['client_id'] = input("Please provide your Plaid API client_id: ")
    conf['PLAID']['client_s'] = getpass.getpass('Please provide your client API Secret: ')
    conf['PLAID']['client_user_id'] = secrets.token_hex(16)
    # Write the initial file
    with open(file, 'wb') as file_handle:
        conf.write_encrypted(file_handle)

# And some static config things...
client_name = "plaid2qfx_python"
plaid_api_configuration = plaid.Configuration(
    host=plaid.Environment.Development, # Available environments are 'Production', 'Development', and 'Sandbox'
    api_key={
        'clientId': conf['PLAID']['client_id'],
        'secret': conf['PLAID']['client_s'],
    }
)


#### Setup and Initialization ####
# Parse arguments
parser = argparse.ArgumentParser()
parser.add_argument("-l", "--linkaccount", action="store_true", help="Link a new account. You'll be prompted later in the script for the link account name.")
parser.add_argument("-a", "--account", help="Use this if you only want to work with a specific account instead of all saved accounts.")
parser.add_argument("-s", "--showaccounts", action="store_true", help="Just enumerate the accounts in config. Access tokens will not be included.")
args = parser.parse_args()

# Start initiation some Plaid endpoints
api_client = plaid.ApiClient(plaid_api_configuration)
client = plaid_api.PlaidApi(api_client)

# DEBUG STUFF TO REMOVE
#args.linkaccount = True
#args.account = "GAOwn"
args.showaccounts = True


#### MAIN ####
def main():
    
    # If we don't have any accounts defined, gotta link one. The first conf section is Plaid API stuff. We need at least two.
    if len(conf.sections()) < 2:
        print("Doesn't look like we have any accounts defined yet. Let's set one up.")
        link_name = link_account()
        print("Thank you. It looks like ", link_name, " was added successfully.")
    
    # Based on argument given, user may want to link more accounts.
    elif args.linkaccount:
        print("Lets add a new linked account.")
        link_name = link_account()
        print("Thank you. It looks like ", link_name, " was added successfully.")
        reply = input("Would you like to go ahead and fetch transactions? (y/n) ")
        if reply == "y" or reply=="yes":
            (added, modified, removed) = get_transactions(link_account)
        else:
            sys.exit(0)

    # If showaccounts was specified in arguments...
    elif args.showaccounts:
        showaccounts()
        sys.exit(0)

    # If a specific account was targeted in arguments...
    elif args.account:
        (added, modified, removed) = get_transactions(args.account)

    # Otherwise, start processing all accounts
    else:
        for section in conf.sections():
            if (section == 'PLAID'):
                continue
            (added, modified, removed) = get_transactions(section)

    sys.exit()


#### New Accounts ####

def link_account():
    if args.account:
        link_name = args.account
    else:
        link_name = input("For the purposes of this script, what label would you like to give this linked account? ")
    
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
    access_token = response['access_token']
    item_id = response['item_id']

    # Enumerate Accounts
    request = AccountsGetRequest(
        access_token=access_token
    )
    response = client.accounts_get(request)
    accounts = response['accounts']
    print("\nAccounts:")
    for item in accounts:
        print(item['name'], end=': ')
        print(item['account_id'])
    
    # Store all of this in our config file
    conf.add_section(link_name)
    conf[link_name]['access_token'] = access_token
    conf[link_name]['item_id'] = item_id
    conf[link_name]['accounts'] = json.dumps(response.to_dict())
    with open(file, 'wb') as file_handle:
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
                    document.getElementById("results").innerHTML = "public_token: " + public_token + "<br>metadata: " + metadata;
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


#### Getting Transactions ####

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

    # Store updated cursor
    conf[link_name]['cursor'] = cursor
    with open(file, 'wb') as file_handle:
        conf.write_encrypted(file_handle)
    
    # Return retrieved data
    return(added, modified, removed)


#### Enumerate Configured Accounts ####
def showaccounts():
    for section in conf.sections():
        if (section == 'PLAID'):
            continue
        print("/nAccount ", conf[section]["link_name"])
        for key in section:
            print("    Key: ", key, end='')
            print("Value: ", conf[section][key])    


if __name__ == "__main__":
    main()