cmake_minimum_required(VERSION 3.16)
project(QtBrowser LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
find_package(Qt6 REQUIRED COMPONENTS Widgets WebEngineWidgets WebEngineCore)

add_executable(QtBrowser main.cpp)
target_link_libraries(QtBrowser PRIVATE Qt6::Widgets Qt6::WebEngineWidgets Qt6::WebEngineCore)
