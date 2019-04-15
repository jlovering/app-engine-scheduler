#!/bin/python

startup_script ='''
#!/bin/bash

DAY_OFFSET=`curl -sS "http://metadata.google.internal/computeMetadata/v1/instance/attributes/day_offset" -H "Metadata-Flavor: Google"`
L_TZ=`curl -sS "http://metadata.google.internal/computeMetadata/v1/instance/attributes/TZ" -H "Metadata-Flavor: Google"`
DOCKER_IMAGE=`curl -sS "http://metadata.google.internal/computeMetadata/v1/instance/attributes/docker_image" -H "Metadata-Flavor: Google"`
BUCKET_URI=`curl -sS "http://metadata.google.internal/computeMetadata/v1/instance/attributes/bucket_uri" -H "Metadata-Flavor: Google"`
SITE_NAME=`curl -sS "http://metadata.google.internal/computeMetadata/v1/instance/attributes/site_name" -H "Metadata-Flavor: Google"`
STARTHH=`curl -sS "http://metadata.google.internal/computeMetadata/v1/instance/attributes/starthh" -H "Metadata-Flavor: Google"`

#Generated Params
RUN_DATE=`TZ=$L_TZ date "+%Y%m%d"`
FCST_DATE=`TZ=$L_TZ date -d "+$DAY_OFFSET days" "+%Y%m%d"`
#SH varies based off timezone and must match parames
let SH=${STARTHH}+$DAY_OFFSET*24

L_USER='jon_lovering'
GSUTIL_CMD='python /mnt/stateful_partition/bin/gsutil/gsutil'

# Update the docker
docker \
    --config="/home/${L_USER}/.docker" \
    pull ${DOCKER_IMAGE}

# Run the model
docker \
    --config="/home/${L_USER}/.docker" \
    run \
    --log-driver=gcplogs \
    --net="host" \
    -v=/var/run/docker.sock:/var/run/docker.sock \
    -v=/etc/profile.d:/host/etc/profile.d \
    -v=/dev:/dev \
    -v=/mnt:/mnt \
    -v=/proc:/host_proc \
    -v /tmp/OUT:/root/rasp/${SITE_NAME}/OUT/ \
    -v /tmp/LOG:/root/rasp/${SITE_NAME}/LOG/ \
    -e START_HOUR=$SH \
    --rm \
    ${DOCKER_IMAGE}

# Upload the output
su $L_USER -c "$GSUTIL_CMD -m cp /tmp/OUT/* ${BUCKET_URI}/${RUN_DATE}/${FCST_DATE}/FCST/"

# Save logs
tar -C /tmp/LOG/ -czvf /tmp/${RUN_DATE}_${FCST_DATE}_logs.tgz .
su $L_USER -c "$GSUTIL_CMD -m cp /tmp/${RUN_DATE}_${FCST_DATE}_logs.tgz ${BUCKET_URI}/logs/"

touch /tmp/${RUN_DATE}_${FCST_DATE}.exists
su $L_USER -c "$GSUTIL_CMD -m cp /tmp/${RUN_DATE}_${FCST_DATE}.exists ${BUCKET_URI}/index/"

# Clean up old dockers
docker image prune -f
docker container prune -f

# Shutdown
shutdown -h now
'''
