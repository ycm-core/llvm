FROM ubuntu:16.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LC_ALL C.UTF-8

RUN apt-get update && \
  apt-get -y dist-upgrade && \
  apt-get -y install software-properties-common && \
  add-apt-repository -y ppa:ubuntu-toolchain-r/test && \
  apt-get update && \
  apt-get -y --no-install-recommends install ca-cacert \
                     locales \
                     tzdata \
                     language-pack-en \
                     git \
                     build-essential \
                     python3-pip \
                     python3-setuptools \
                     p7zip-full \
                     sudo \
                     gcc-9 \
                     g++-9 && \
  update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-9 1 \
                      --slave   /usr/bin/g++ g++ /usr/bin/g++-9 && \
  apt-get -y autoremove

RUN ln -fs /usr/share/zoneinfo/Europe/London /etc/localtime && \
  dpkg-reconfigure --frontend noninteractive tzdata

# Get a recent cmake
RUN pip3 install cmake requests debugpy

# clean up
RUN rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* &&\
    rm -rf ~/.cache
