FROM fluent/fluentd:v1.16-debian-1

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential libffi-dev && \
    fluent-gem install elasticsearch -v 7.17.11 && \
    fluent-gem install fluent-plugin-elasticsearch -v 5.4.3 && \
    apt-get purge -y build-essential && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

USER fluent
