include_directories(${TOPDOWN_INCLUDE_DIR})

set(CALIPER_TOPDOWN_SOURCES
    Topdown.cpp)

add_library(caliper-topdown OBJECT ${CALIPER_TOPDOWN_SOURCES})

add_service_objlib("caliper-topdown")
add_caliper_service("topdown CALIPER_HAVE_LIBPFM")
