FROM ubuntu:16.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LC_ALL C.UTF-8

RUN apt-get update && \
  apt-get -y dist-upgrade && \
  apt-get -y --no-install-recommends install ca-cacert \
                     locales \
                     tzdata \
                     language-pack-en \
                     git \
                     build-essential \
                     python3-pip \
                     python3-setuptools \
                     p7zip-full \
                     sudo && \
  apt-get -y autoremove

RUN ln -fs /usr/share/zoneinfo/Europe/London /etc/localtime && \
  dpkg-reconfigure --frontend noninteractive tzdata

# Get a recent cmake
RUN pip3 install cmake requests debugpy

# clean up
RUN rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* &&\
    rm -rf ~/.cache
