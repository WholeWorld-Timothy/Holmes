#!/bin/bash
export LANG=en_US.UTF-8
function line() {
    line=""
    for (( i=1; i<=30; i++ )); do
        line="$line-"
    done
    echo "$line"
}
echo "begin"
line
# check system
if [ "$(lsb_release -si)" = "Ubuntu" ] && [ "$(lsb_release -rs | cut -d. -f1)" -ge 16 ]; then
    echo "System check ok!"
else
    exit 1
fi
# check python
if command -v python3 &>/dev/null; then
    python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
    if [ "$(echo "$python_version 3.8" | awk '{print ($1 >= $2)}')" -eq 1 ]; then
        echo "check python ok!"
    else
        echo "need python 3.8+"
    fi
else
    echo "need python3.8+"
    # shellcheck disable=SC2162
    read -p "auto install python3.8 ？(Y/N): " confirm
    if [[ $confirm == "Y" || $confirm == "y" ]]; then
        sudo apt update
        sudo apt install python3.8
    else
        exit 1
    fi
fi
line
# check redis and install
# shellcheck disable=SC1009
if command -v redis-server &>/dev/null; then
    echo "Redis has installed"
    # shellcheck disable=SC1073
    # shellcheck disable=SC1049
    if systemctl is-active --quiet redis; then
        echo "redis is ok"
    else
        echo "start redis.. "
        sudo service redis-server start
    fi
else
    # shellcheck disable=SC2162
    read -p "auto install redis ？(Y/N): " confirm
    if [[ $confirm == "Y" || $confirm == "y" ]]; then
        sudo apt update
        echo "redis install ......"
        sudo apt-get -y install redis-server
        echo "start redis.. "
        sudo service redis-server start
        sudo systemctl enable redis-server
    else
        exit 1
    fi
fi
line
# install postgresql
# shellcheck disable=SC1009
if ! command -v psql &> /dev/null; then
    # shellcheck disable=SC2162
    read -p "auto install postgresql16 ？(Y/N): " confirm
    if [[ $confirm == "Y" || $confirm == "y" ]]; then
        echo "begin install postgresql"
        echo "set postgresql source "
        sudo wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
        echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
        sudo apt-get update
        sudo apt-get install postgresql-16 -y
        echo "start postgresql"
        sudo service postgresql start
        echo "you can run 'sudo -i -u postgres' manage database "
    else
      echo "need postgresql"
      exit 1
    fi
else
    echo "you have installed postgresql"
fi
echo "start postgresql"
sudo service postgresql start
echo "create database holmes"
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw holmes; then
    echo "Database 'holmes' already exists."
else
    sudo -u postgres psql -c "CREATE DATABASE holmes;"
    echo "Database 'holmes' created."
fi
# shellcheck disable=SC2006
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='holmes'" | grep -q 1; then
     echo "User 'holmes' created."
else
     sudo su postgres -c "`printf 'psql -c "create user holmes password %s;"' "'holmes_8338'"`"
fi
echo "change database owner"
sudo -u postgres psql -c "ALTER DATABASE holmes OWNER TO holmes;"
echo "Setting user and database can connect"
sudo sh -c "sed -i '/^#\s*TYPE/ahost holmes holmes 127.0.0.1/32  md5' /etc/postgresql/16/main/pg_hba.conf && service postgresql restart "

line
echo "install sys extends"
# shellcheck disable=SC1004
sudo dpkg --remove-architecture i386
sudo apt-get update &&  apt-get install -y python3-pip \
    libaio1 libaio-dev alien curl gnupg build-essential pwgen libffi-dev git-core wget \
    libpq-dev g++ unixodbc-dev xmlsec1 libssl-dev default-libmysqlclient-dev freetds-dev \
    libsasl2-dev unzip libsasl2-modules-gssapi-mit
line
echo "init virtual vevn"
pip install virtualenv
echo "create venv"
virtualenv venv -p python3
echo "activate venv"
source venv/bin/activate
line
echo "set pip config"
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install --upgrade pip
line
echo "need python require"
pip install -r requirements.txt -r requirements_ai.txt
line
# check mysql config file
if [ -f /usr/include/mysql/my_config.h ]; then
    echo "mysql config file is ok"
else
  if [ -f /usr/include/mysql/mysql.h ]; then
      sudo ln -s /usr/include/mysql/mysql.h  /usr/include/mysql/my_config.h
  else
      echo "mysql config file is not ok, please check  /usr/include/mysql/my_config.h exsist or not "
      exit 1
  fi
fi

line
echo "check front extends"
line
if command -v node &>/dev/null; then
    echo "node is ok"
else
    sudo apt-get update
    sudo apt-get -y install nodejs npm
fi
line

if command -v n &>/dev/null; then
    echo "node manager n is ok"
else
    sudo npm install n -g
fi
echo "node manager n is ok"
line
echo "install  node version 14.17"
sudo n 14.17
line
# check node is version 14.17
while true; do
    node_version=$(node -v)
    if [[ "$node_version" == "v14.17"* ]]; then
      break
    else
        echo "node version is not 14.17.*, please select it"
        sudo n
    fi
done
line
echo "make .env config file"
#
if [ -f .env ]; then
    rm .env
fi
# get local ip
ip_addresses=$(ifconfig | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*')
# print ip for user to select the ip
echo "You local ip as fellows:"
echo "$ip_addresses" | tr ' ' '\n'

# let user select ip
echo "Please select a ip for your server, you can change it at .env file:"
while true; do
    # shellcheck disable=SC2162
    read -p "Please input your ip: " ip
    if [[ $ip == "" ]]; then
        echo "Ip mast input"
    else
        # shellcheck disable=SC2162
        read -p "You input this: $ip  ,Are you sure？(Y/N): " confirm
        if [[ $confirm == "Y" || $confirm == "y" ]]; then
            echo "IP ：$ip"
            break
        fi
    fi
done
# shellcheck disable=SC2162
read -p "We need server port 8338 8339 ,is that ports not use？(Y/N): " confirm
if [[ $confirm == "N" || $confirm == "n" ]]; then
    exit 1
fi
# get web port
# shellcheck disable=SC2162
web_port=8338
# get socket port
# shellcheck disable=SC2162
socket_port=8339
# get env_template content
env_content=$(cat .env.template)
# replace postgresql
# shellcheck disable=SC2001
env_content=$(echo "$env_content" | sed "s/# HOLMES_DATABASE_URL=\"postgresql:\/\/user:pwd@ip\/database\"/HOLMES_DATABASE_URL=\"postgresql:\/\/holmes:holmes_8338@127.0.0.1\/holmes\"/g")
# replace redis
# shellcheck disable=SC2001
env_content=$(echo "$env_content" | sed "s/# HOLMES_REDIS_URL/HOLMES_REDIS_URL/g")
# replace language
# shellcheck disable=SC2001
env_content=$(echo "$env_content" | sed "s/LANGTYPE/EN/g")
# replace web port
# shellcheck disable=SC2001
env_content=$(echo "$env_content" | sed "s/WEB_PORT/$web_port/g")
# replace language
# shellcheck disable=SC2001
env_content=$(echo "$env_content" | sed "s/SOCKET_PORT/$socket_port/g")
# replace ip
# shellcheck disable=SC2001
env_content=$(echo "$env_content" | sed "s/IP/$ip/g")
# replace sec_key
sec_key=$(openssl rand -hex 16)
# shellcheck disable=SC2001
env_content=$(echo "$env_content" | sed "s/SEC_KEY/$sec_key/g")
# set user upload dir

# save .env file
echo "$env_content" > .env
root=$(pwd)
echo "DATA_SOURCE_FILE_DIR=$root/user_upload_files" >> .env


if command -v yarn &>/dev/null; then
    echo "yarn manager n is ok"
else
    sudo npm install yarn -g
fi
line

sudo yarn config set registry https://registry.npmmirror.com
sed -i 's#github.com/getredash/sql-formatter.git#gitee.com/apgmer/sql-formatter.git#g'  yarn.lock
line

echo "begin build web page"
sudo yarn && yarn build
line

source venv/bin/activate

line
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
if [[ "$python_version" == "3.8."* ]]; then
    echo "修复 python3.8 bug"
    sed -i 's/from importlib_resources import path/from importlib.resources import path/g' ./venv/lib/python3.8/site-packages/saml2/sigver.py &&
    sed -i 's/from importlib_resources import path/from importlib.resources import path/g' ./venv/lib/python3.8/site-packages/saml2/xml/schema/__init__.py
    line
fi

echo "init database "
./bin/run ./manage.py database create_tables
line
# start server backend
echo "start server"
nohup ./bin/run ./manage.py runserver -h0.0.0.0  -p "$web_port" >web.log 2>&1 &
nohup ./bin/run ./manage.py rq scheduler >scheduler.log 2>&1 &
nohup ./bin/run ./manage.py rq worker  >worker.log 2>&1 &
nohup ./bin/run ./manage.py run_ai  >ai.log 2>&1 &
echo "--------------------------------"
echo "You can visit http://$ip:$web_port"
echo "--------------------------------"







