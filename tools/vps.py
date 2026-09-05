"""Передача релиза по SSH с проверкой известного ключа хоста; пароль не сохраняется."""
import argparse
import getpass
import sys
import shlex
from pathlib import Path
import paramiko

parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['upload','run'])
parser.add_argument('source')
parser.add_argument('destination',nargs='?')
parser.add_argument('--sudo',action='store_true')
args=parser.parse_args()
client=paramiko.SSHClient()
client.load_host_keys(str(Path.home()/'.ssh'/'known_hosts'))
password=getpass.getpass('SSH password: ')
client.connect('89.111.171.30',username='florama',password=password,timeout=15,look_for_keys=False,allow_agent=False)
try:
    if args.action=='upload':
        with client.open_sftp() as sftp:
            sftp.put(args.source,args.destination)
        print('Upload complete',flush=True)
    else:
        command='sudo -S -p "" bash -lc '+shlex.quote(args.source) if args.sudo else args.source
        stdin,stdout,stderr=client.exec_command(command,timeout=1200)
        if args.sudo:
            stdin.write(password+'\n');stdin.flush()
        for line in iter(stdout.readline,''):
            print(line.rstrip(),flush=True)
        print(stderr.read().decode(),file=sys.stderr)
        sys.exit(stdout.channel.recv_exit_status())
finally:
    client.close()
