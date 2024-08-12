Makes a graphical representation of a STAN-model using graphviz

# Installation
Run :
```bash
make
make append_main_function
```
In order to generate an executable python script and apply "run-as-main"-functionallity to it. 

# Running
then in order to generate the graph of the STAN-model, run:
```bash
python3 graph_stan.py [filename].stan
```
execiting the generated script. 

The resulting generated files are:
- a dot file containing the code for generating a graph using graphviz
- a .png from running the dot file though graphviz

# Reinstall
```bash
make clean
```

Deletes the generated .py files in the directory. 
