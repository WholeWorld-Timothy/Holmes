#!/bin/bash
export LANG=en_US.UTF-8
if [ -f .env ]; then
    rm .env
fi

if [ -f Dockerfile ]; then
    rm Dockerfile
fi
# Install.sh, you mast have installed docker and docker-compose
# check docker support
if ! command -v docker &> /dev/null; then
    echo "Docker has not installed. Solve this problem : https://github.com/Deep-thoughtIO/holmes/InstallDocker.md"
    exit 1
fi

# check Docker Compose support
if ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose has not installed. Solve this problem : https://github.com/Deep-thoughtIO/holmes/InstallDocker.md"
    exit 1
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
# save .env file
echo "$env_content" > .env
cp Dockerfile.template Dockerfile
# save env file over
echo "You setting as fellows:"
echo "--------------------------------"
echo "$env_content"
echo "--------------------------------"
# begin run docker compose
echo "Next, we will pull the image created by docker-compose.
      Depending on your network environment, it will cost half an hours or more "

docker-compose build
echo "--------------------------------"
echo "build over. Create database container and init database"
docker-compose run --rm server create_db
echo "Initialization database completed"
echo "--------------------------------"
echo "command: "
echo " docker-compose up  #Create containers and front-end command line operation "
echo " docker-compose up -d # Create containers and start containers server in the background: "
echo " docker-compose start # Start all containers server "
echo " docker-compose start [container id /container name]# Start signal container server"
echo " docker-compose stop [container id /container name]# Stop signal container server"
echo " docker-compose ps # look all containers server running info"
echo "--------------------------------"
echo "Run: docker-compose up......"
docker-compose up -d
echo "--------------------------------"
echo "You can visit http://$ip:$web_port"
echo "--------------------------------"


