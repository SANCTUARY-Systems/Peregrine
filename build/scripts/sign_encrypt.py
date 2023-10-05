#!/usr/bin/env python3

try:
    from Cryptodome.Signature import pss
    from Cryptodome.Signature import pkcs1_15
    from Cryptodome.Hash import SHA256
    from Cryptodome.PublicKey import RSA
except ImportError:
    from Crypto.Signature import pss
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA256
    from Crypto.PublicKey import RSA
import base64
import logging
import os
import struct
import sys
import subprocess

algo = {'TEE_ALG_RSASSA_PKCS1_PSS_MGF1_SHA256': 0x70414930,
        'TEE_ALG_RSASSA_PKCS1_V1_5_SHA256': 0x70004830}


def uuid_parse(s):
    from uuid import UUID
    return UUID(s)


def int_parse(str):
    return int(str, 0)


def get_args(logger):
    from argparse import ArgumentParser, RawDescriptionHelpFormatter
    import textwrap
    command_base = ['sign']

    parser = ArgumentParser(
        description='Cryptographic operations for the Peregrine manifest\n',
        usage='\n   %(prog)s command [ arguments ]\n\n'

        '   command:\n' +
        '     sign    Generate signature of Peregrine manifest file.\n' +
        '                 Takes arguments --uuid, --key, --img_path, --img_version --out_file\n' +
        '   %(prog)s --help  show available commands and arguments\n\n',
        formatter_class=RawDescriptionHelpFormatter,
        epilog=textwrap.dedent('''\
            If no command is given, the script will default to "sign".

            example signing command using OpenSSL for algorithm
            TEE_ALG_RSASSA_PKCS1_PSS_MGF1_SHA256:
              base64 -d <UUID>.dig | \\
              openssl pkeyutl -sign -inkey <KEYFILE>.pem \\
                  -pkeyopt digest:sha256 -pkeyopt rsa_padding_mode:pss \\
                  -pkeyopt rsa_pss_saltlen:digest \\
                  -pkeyopt rsa_mgf1_md:sha256 | \\
              base64 > <UUID>.sig\n
            example signing command using OpenSSL for algorithm
            TEE_ALG_RSASSA_PKCS1_V1_5_SHA256:
              base64 -d <UUID>.dig | \\
              openssl pkeyutl -sign -inkey <KEYFILE>.pem \\
                  -pkeyopt digest:sha256 -pkeyopt rsa_padding_mode:pkcs1 | \\
              base64 > <UUID>.sig
            '''))

    parser.add_argument('command', choices=command_base, nargs='?', default='sign',
                        help='Command, one of [' + ', '.join(command_base) + ']')  
    # Don't use the UUID type
    #parser.add_argument('--uuid', required=True,
    #                    type=uuid_parse, help='String UUID of the TA')
    parser.add_argument('--uuid', required=True, dest='uuid',
                        help='String UUID of the manifest')   
    parser.add_argument('--version', required=True, type=int_parse, dest='version',
                        help='Manifest version') 
    parser.add_argument('--key', required=True, dest='key',
                        help='Path to the signing key file (PEM format)')
    parser.add_argument('--img_path', required=True, dest='img_path',
                        help='Path to the manifest file')
    parser.add_argument('--out', required=True, dest='out_file',
                        help='Output signature file')
    parser.add_argument('--algo', required=False, choices=list(algo.keys()),
                        default='TEE_ALG_RSASSA_PKCS1_PSS_MGF1_SHA256',
                        help='The hash and signature algorithm, ' +
                        'defaults to TEE_ALG_RSASSA_PKCS1_PSS_MGF1_SHA256. ' +
                        'Allowed values are: ' +
                        ', '.join(list(algo.keys())), metavar='')
    parsed = parser.parse_args()

    # Check parameter combinations
    if parsed.out_file is None:
        logger.error('No output file specified.')
        sys.exit(1)

    return parsed


def write_digest(digf, digest):
    with open(digf, 'wb+') as digfile:
        digfile.write(digest)
 
        
def write_signature(sigf, signature):
    with open(sigf, 'wb+') as sigfile:
        sigfile.write(signature)


def get_digest(uuid, img_path, version):

    with open(img_path, 'rb') as f:
        img = f.read()

    uuid_raw = uuid.encode('ASCII')
    version_pack = struct.pack('<I', version)

    h = SHA256.new()
    h.update(uuid_raw)
    h.update(version_pack)
    h.update(img)

    return h.digest()

 
def get_sign(key, digest):
    arg_string = ['openssl', 'pkeyutl', '-sign', '-inkey', key, '-pkeyopt', 'digest:sha256', '-pkeyopt', 'rsa_padding_mode:pss', '-pkeyopt', 'rsa_pss_saltlen:digest', '-pkeyopt', 'rsa_mgf1_md:sha256']

    try:
        out = subprocess.Popen(arg_string, stdin=subprocess.PIPE, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
        signature = out.communicate(digest)[0] # (stdout, stderr)
        return signature
    except subprocess.CalledProcessError as e:
        print("Error during signing: " + e.output)
 
 
def vm_gen_digest(uuid, img_path, version):

    digest = get_digest(uuid, img_path, version)  
    return base64.b64encode(digest)       
   
        
def vm_gen_sig(uuid, key, img_path, version):

    digest = get_digest(uuid, img_path, version)
    signature = get_sign(key, digest)
    
    return base64.b64encode(signature)


def main():
    logging.basicConfig()
    logger = logging.getLogger(os.path.basename(__file__))

    args = get_args(logger)  
    
    if args.command in ['sign']:
        signature = vm_gen_sig(args.uuid, args.key, args.img_path, args.version)
        write_signature(args.out_file, signature)
    else:
        logger.error('Command ' + parse.command + ' not found.')
        sys.exit(1)


if __name__ == "__main__":
    main()
