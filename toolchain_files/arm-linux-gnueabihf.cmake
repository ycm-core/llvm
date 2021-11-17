set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR arm)

set($ENV{CFLAGS} "-mcpu=generic-armv7-a")
set($ENV{CXXFLAGS} "-mcpu=generic-armv7-a")

set(CMAKE_C_FLAGS "-mcpu=generic-armv7-a")
set(CMAKE_CXX_FLAGS "-mcpu=generic-armv7-a")
