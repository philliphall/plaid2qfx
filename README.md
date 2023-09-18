# plaid2qfx

## Description
This is a Python script that leverages the [Plaid API](https://plaid.com/docs/) to download transactions and format them into QFX files for import into [Quicken](https://www.quicken.com/). (If anyone wants, I can very easily add an OFX format option for use with other financial software.)

### Why?
Frankly, to solve a very specific pet peeve I had. After 20+ years of using Quicken, I discovered I really liked using SoFi as my primary bank. Unfortunately, SoFi doesn't support Quicken for Windows (only Quicken for Mac, go figure). And SoFi doesn't offer anything but a super lame CSV exports of transactions on a per-account basis. 

Well why not just use the CSV file and something like ImportQIF you ask? Because the QIF format, just like SoFi's CSV exports, lacks a unique transaction ID that prevents duplicating transactions. And various other irritations. It just drove me nuts. My way is far superior :-) !

## Instructions
If you are already intimidated at the idea of running a Python script, this is not for you. But please leave me a comment and if I get enough interest, I'll consider figuring out how to create a web app version.

### A few requirements:
* A working Pyton 3 installation plus some non-standard modules: 
  - [plaid-python](https://github.com/plaid/plaid-python) - Official module from Plaid
  - [ofxtools](https://github.com/csingley/ofxtools) - Enforces compliance with the OFX standard
  - [configparser_crypt](https://pypi.org/project/configparser-crypt/) - Secure storage
* A free [Plaid developer account](https://dashboard.plaid.com/signup)
  - Once you have your account, [check here](https://dashboard.plaid.com/overview/development) to see how many Live Credentials you have availalbe and request up to 100. Some accounts start with 5, mine for some reason started with 0. 
* A bank account that Plaid supports for transaction downloads, which you need a developer account to fully search. 
  - Search for your bank [here](https://dashboard.plaid.com/activity/status) and make sure it lists * *Transactions* * under Supported Products

### Usage
Just run the script and it should prompt you through the rest. There are some options that may be useful after you are set up and working:
```
PS C:\Git\plaid2qfx> py plaid2qfx.py --help
usage: plaid2qfx.py [-h] [-u] [-l] [-s] [-a ACCOUNT]

options:
  -h, --help            show this help message and exit
  -u, --updateconf      Update previously stored API and other configuration items, then exit.
  -l, --linkaccount     Link an additional account. You'll be prompted interactively for the link account name.
  -s, --showaccounts    Just enumerate the linked accounts in config then exit. Access tokens will NOT be displayed.
  -a ACCOUNT, --account ACCOUNT
                        Use this if you only want to work with a specific linked account instead of all saved
                        accounts. Use the label you specified for this account when first set up.
```

## Security and How It Works
1. The first thing that happens when you run the script is that it will create an **AES 256-bit encrypted** configuration file `plaid2qfx.conf` in your working directory. This will securely store your Plaid developer API key and secret, as well as the access tokens for bank accounts you link via Plaid. You will be given a key that you must store safely (I recommend a password manager) and paste interactively into the script each time you run it. If you insist on the convenience of not having to interactively provide that key, you will have to modify the code yourself, and I take no responsibility because I don't recommend it.
2. Next, you will be asked for your Plaid API client_id and secret. These will be encrypted and stored as part of your config.
3. Then you will be asked where you would like to save QFX output files. I didn't really want those living in my working directory and accidently getting synced to my GitHub repo!
4. Now you get to set up a Plaid linked account.
   - Give it a name. I use a simple abbreviation of my Bank name. "PLAID" and "DEFAULT" are reserved for other uses.
   - An .html file will be generated containing the first step in Plaid's Link flow. If you're security-conscious like me, open the html file in a text editor and verify that the only script content comes directly from Plaid.com and a small script block in the html file that writes the public token Plaid returns when you complete a link to your screen. Now that you feel safe, open that file in your browser and click the button to interface with Plaid.
> [!WARNING]
> I take no responsiblity for Plaid's handling of your credentials, their privacy practices, or their security overall. Plaid * *is* * a reputable vendor, and this script does * *not* * have any access to your credentials. But I do think everyone should think twice before entering their Bank password anywhere that isn't their Bank.
   - Once you complete the Plaid workflow, you should see a public_token on the web page. Copy that and paste it into the script. The script will complete the token exchange and receive and securely store an access token allowing the script to download transactions from your Bank any time you run it.
   - The script will get a couple more details, clean up the .html file and move on to downloading transactions and formatting them in a QFX file for you.


## Caveats and Known Issues
1. The .html file generated as part of the account linking process does not work properly in Firefox. You'll get a spinning circle when you click the button. Chrome and Edge work fine.


