#!/usr/bin/env python

import logging
import kubernetes
import os
import random
import time
import pytz
import json
import datetime

from kubernetes.client.rest import ApiException
from http import HTTPStatus


POD_NAME = os.environ.get('CHAOS_MONKEY_POD_NAME')
KILL_FREQUENCY = int(os.environ.get('CHAOS_MONKEY_KILL_FREQUENCY_UPPER_LIMIT', 36000))
LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)

# No error handling, if things go wrong Kubernetes will restart for us!

kubernetes.config.load_incluster_config()
v1 = kubernetes.client.CoreV1Api()

while True:
    pods = v1.list_pod_for_all_namespaces().items
    pod = next(pod for pod in pods if pod.metadata.labels["name"] == POD_NAME)
    LOGGER.info("Terminating pod %s/%s", pod.metadata.namespace, pod.metadata.name)
    event_name = "Chaos monkey kill pod %s" % pod.metadata.name
    v1.delete_namespaced_pod(
        name=pod.metadata.name,
        namespace=pod.metadata.namespace,
        body=kubernetes.client.V1DeleteOptions(),
    )
    event_timestamp = datetime.datetime.now(pytz.utc)
    try:
        event = v1.read_namespaced_event(event_name, namespace=pod.metadata.namespace)
        event.count += 1
        event.last_timestamp = event_timestamp
        v1.replace_namespaced_event(event_name, pod.metadata.namespace, event)
    except ApiException as e:
        error_data = json.loads(e.body)
        error_code = HTTPStatus(int(error_data['code']))
        if error_code == HTTPStatus.NOT_FOUND:
            new_event = kubernetes.client.V1Event(
                count=1,
                first_timestamp=event_timestamp,
                involved_object=kubernetes.client.V1ObjectReference(
                    kind="Pod",
                    name=pod.metadata.name,
                    namespace=pod.metadata.namespace,
                    uid=pod.metadata.uid,
                ),
                last_timestamp=event_timestamp,
                message="Pod deleted by chaos monkey",
                metadata=kubernetes.client.V1ObjectMeta(
                    name=event_name,
                ),
                reason="ChaosMonkeyDelete",
                source=kubernetes.client.V1EventSource(
                    component="chaos-monkey",
                ),
                type="Warning",
            )
            v1.create_namespaced_event(namespace=pod.metadata.namespace, body=new_event)
        else:
            raise
    time.sleep(random.randrange(30, KILL_FREQUENCY))
