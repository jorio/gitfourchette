@echo off
:: Can't redirect UserKnownHostsFile to /dev/null or NUL!
:: ssh will create an actual 'NUL' file that Windows will refuse to delete.
ssh ^
    -F none ^
    -o IdentityFile=none ^
    -o StrictHostKeyChecking=no ^
    -o UserKnownHostsFile=%~dp0\isolated-ssh.tmp ^
    %*
