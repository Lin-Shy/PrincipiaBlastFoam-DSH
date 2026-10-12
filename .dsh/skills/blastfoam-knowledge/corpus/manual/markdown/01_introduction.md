# Introduction

blastFoam is an opensource computational fluid dynamics (CFD) code based on the OpenFOAM C++ library (OpenCFD Ltd., 2018a) to simulate strongly compressible systems of equations with detonations. Along with the main solvers for simulating fluid flow, additional utilities have been added to simplify case setup, allow adaptive mesh refinement with load balancing based on the work of Rettenmaier et al. (2019), and facilitate blastFoam specific case post-processing.

The purpose of this guide is to serve as a reference for the governing equations and the models that have been implemented in blastFoam. The guide also provides a brief description of the capabilities of the solver and the new utilities that have been introduced on top of those available in the standard OpenFOAM. Many of the available models include options that the user can tune to best suit their simulations, and are given in a table at the end of each model description.

## System Requirements

blastFoam currently builds against OpenFOAM-9 2. The following dependencies are required to successfully compile and run blastFoam:

1. A working installation of OpenFOAM-9 complete with libraries and headers produced by OpenFOAM-9, no other packages are required to run blastFoam applications. If OpenFOAM-9 is compiled from source, the ThirdParty-9 repository source is also required. If a pre-compiled version of OpenFOAM-9 is used, this is automatically installed.

2. In order to create and view the postscript plots (e.g. `*.eps` files), gnuplot is available on all platforms. EPS Viewer can be used on Windows and ghostview can be used on linux. On macOS, Preview opens eps files natively.

2https://github.com/OpenFOAM/OpenFOAM-9

## Downloading

The un-compiled source code can be obtained at: https://github.com/synthetik-technologies/blastfoam. Download or clone the source in the following location: `$HOME/OpenFOAM/blastfoam`

```sh
mkdir -p $HOME/OpenFOAM # create the OpenFOAM directory
cd $HOME/OpenFOAM # go to the directory
git clone https://github.com/synthetik-technologies/blastfoam
```

## Compilation

After cloning the the blastFoam source code from https://github.com/synthetik-technologies/blastfoam (see previous section) and installing any optional libraries, similar to OpenFOAM, add the following line to `$HOME/.bashrc` file:

```sh
source ~/OpenFOAM/blastfoam/etc/bashrc
```

and run:

```sh
source ~/.bashrc
```

in any open terminals to update the BASH environment. This is used to specify the local directories included during blastFoam compilation, as well as make future developments easier and less intrusive.

Next run the `./Allwmake` command from the top blastFoam directory to compile the libraries and applications. Finally, ensure that OpenFOAM-9 and blastFoam have been installed and that the environment has been correctly setup by running one of the tutorial or validation cases.

Summary of steps to download, configure and compile blastFoam:

```sh
# 1. create the OpenFOAM directory if if does not exist
mkdir -p $HOME/OpenFOAM
# 2. go to the $HOME/OpenFOAM directory
cd $HOME/OpenFOAM
# 3. # clone the blastFoam repository
git clone https://github.com/synthetik-technologies/blastfoam
# go to the blastfoam directory
cd $HOME/OpenFOAM/blastfoam
# Source the etc/bashrc to your .bashrc file
# by runngin the following command in terminal
echo "source $HOME/OpenFOAM/blastfoam/etc/bashrc" >> $HOME/.bashrc
# Re-load and set the bash environment to compile blastFoam
source $HOME/.bashrc
# Compile blastFoam (for parallel use "-j")
./Allwmake
```

## Executable

The applications to solve these equations are executed by running the executable name (i.e. `blastFoam`). The executables are stored within the `$BLAST_APPBIN` (`$FOAM_USER_APPBIN` by default but this can be overridden) directory and can be run from any directory.

## Getting Help

This guide is intended to cover the major points of the library. For more specific questions regarding the equations or models, the references listed in the class header files (`*.H`) should be consulted.

Please report bugs using the issues tab on the GitHub page: https://github.com/synthetik-technologies/blastfoam/issues
