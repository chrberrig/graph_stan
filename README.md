# Graphical representation of a STAN-model

This tool generates and visualizes dependency graphs from a Stan model file. 
The tool uses Graphviz to create graphical representations of the dependencies within a Stan model, supporting features like label customization and verbosity control.

The goal is currently not to make a 100% perfect graphical rendition of a STAN model, but to make a shortcut of the first 90%.

# Quick start
Currently, you run the python script from repository directory (or any location you move it to) as a script, no further installation required. 

In order to generate the graph of the STAN-model, run:
```bash
python3 graph_stan.py path/to/file.stan
```
executing the generated script. 

The resulting generated files are:
- a .dot file containing the code for generating a graph using graphviz
- a .png from running the dot file though graphviz


## Features

- **Graph Rendering**: Automatically generates a dependency graph from a Stan model file, showing the relationships between parameters and data.
- **Custom Labels**: Supports custom labeling of nodes using a label mapping file. This allows for LaTeX-style symbols or any other custom labels.
- **Verbosity Control**: Provides a command-line flag to control the level of detail shown in the dependency graph. You can choose to display full functional dependencies or only the names of the distributions.
- **Flexible Output**: Generates both .dot files for further customization and .png images for easy visualization.

## Installation

Ensure you have the following installed on your system:

**Python**: Make sure Python is installed. The tool is compatible with Python 3.
**Graphviz**: Install Graphviz for rendering the graphs.
**dot2tex**: Install dot2tex if you need LaTeX support.

### Installing Dependencies

Use the following commands to install required dependencies:
```bash
sudo apt-get install graphviz          # Install Graphviz on Debian/Ubuntu
```
While not a strict dependency, it is recommended to install
```bash
pip install graphviz dot2tex           # Install the Python libraries
```
to leverage the tool with LaTeX for latex-style labeling. 

## Usage
Basic Command

To generate a dependency graph from a Stan model file:
```bash
python3 graph_stan.py [options] <stan_file>
```

# Command-Line Options

- -s, --squish: Squish out variables from the dependency tree. Multiple variables can be specified.
- -l, --labels: Specify the path to a label mapping file for custom node labels.
- -v, --verbose: Show full expressions for the dependencies (default is to show only the distribution names).

## Example Commands

1. Generate a Graph with Default Labels
```bash
python3 graph_stan.py example_hierarchical_linreg_iris.stan
```

2. Generate a Graph with Custom Labels
```bash
python3 graph_stan.py -l labels.txt example_hierarchical_linreg_iris.stan
```
Where labels.txt might look like:

```plaintext
alpha \alpha
beta \beta
sigma \sigma
```

Note here that graphviz have some limitations of rendering symbols, like latex syntax, and the labels should be represented in Unicode. 

3. Generate a Graph with Verbosity Control
```bash
python3 graph_stan.py -v example_hierarchical_linreg_iris.stan
```

## Output Files

- dependencies.dot: The generated .dot file representing the dependency graph.
- dependencies.png: The rendered image of the dependency graph.

## Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request with improvements or bug fixes.
