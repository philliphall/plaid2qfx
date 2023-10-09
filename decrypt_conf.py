#######################################
# This quick script is used to convert your configuration file from the encrypted version used prior to 10/9/2023 
# to the unencrypted version used after. 
# 
# This will be the last time you need your special key for decrypting your conf file. From now on, you will enter
# your Plaid client secret interactively, meaning your Plaid secret, which is more sensitive than individual 
# access tokens, is not stored by the script any more. It also means you can edit your configuration text file
# much more easily. 

#### Imports #### 
import sys
import os.path
from configparser import ConfigParser
import getpass

# Non-standard Dependencies
from configparser_crypt import ConfigParserCrypt

# Most of this is managed in an config file stored wherever the script is run.
conffile = 'plaid2qfx.conf'
newconf = ConfigParser()
oldconf = ConfigParserCrypt()

def convertaccounts():
    for section in oldconf.sections():
        print("\nLinked Account --- " + section)
        newconf.add_section(section)
        for key in oldconf[section]:
            if (section == 'PLAID' and key == 'client_s'):
                continue
            print("    Key: " + key.ljust(15), end='  ')
            print("Value: " + oldconf[section][key])
            newconf[section][key] = oldconf[section][key]
    with open(conffile, 'w') as file_handle:
        newconf.write(file_handle)
    print("Configuration updated.")    

if os.path.exists(conffile):
    try:
        hexkey = getpass.getpass("Your configuration key: ")
        oldconf.aes_key = bytes.fromhex(hexkey)
        oldconf.read_encrypted(conffile)
        # Back it up
        os.rename(conffile, conffile+".bak")
        convertaccounts()
    except:
        print("I was unable to open the configuration file. You may not have provided the right key. Exiting.")
        sys.exit(404)

else:
    print("Unable to read file")
