#!/usr/bin/env python
# coding: utf-8

import re
import graphviz
import argparse


def remove_comments(content):
    content = re.sub(r'//.*', '', content)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    return content

def find_defined_parameters(content):
    """
    Finds and returns a set of defined parameters in a Stan file based on their type declaration.

    TODO: 
        Need an input for block type as well, 
        such that a record can be made of the defined parameter being
        either data, parameret, transformed parameter or generated quant. 
        
    Parameters:
    - content: The content of the Stan file as a string.

    Returns:
    - A set of parameter names that are defined in the content.
    """
    # Regular expression to match parameter declarations
    type_pattern = r'\b(int|real|vector|matrix|array)\b(?:<.*?>)?(?:\[[^\]]*\])?\s+(\w+)'
    
    defined_parameters = set()

    # Split content into lines and search for matches
    lines = content.splitlines()
    for line in lines:
        line = line.strip()

        # Find matches for the types
        match = re.search(type_pattern, line)
        if match:
            param_name = match.group(2)  # The variable name is captured in the second group
            defined_parameters.add(param_name)

    return defined_parameters

def find_all_blocks(content):
    blocks = {}
    block_pattern = r'(\w+)\s*\{'
    matches = re.finditer(block_pattern, content)

    for match in matches:
        block_name = match.group(1)
        start = match.end()
        curly_brackets = 1
        end = start

        while curly_brackets > 0 and end < len(content):
            if content[end] == '{':
                curly_brackets += 1
            elif content[end] == '}':
                curly_brackets -= 1
            end += 1
        
        block_content = content[start:end-1].strip()
        blocks[block_name] = block_content
    
    return blocks

def extract_dependencies(expression, defined_params):
    """
    Extracts dependencies from an expression, filtering out integers and indices.
    """
    # Find all potential dependencies
    candidates = re.findall(r'\b(\w+)\b', expression)
    
    # Filter out everything not a parameter or data
    dependencies = [dep for dep in candidates if dep in defined_params]
    
    return dependencies


# def variable_type(relation): 
#     return (relation=="=")*"Deterministic" + (relation=="~")*"Stochastic",
            
def parse_line(line, defined_params):
    """
    Parses a line to identify the variable, its distribution type, and its dependencies.
    
    Parameters:
    - line: The line to parse.
    - defined parameters: Collection of defined parameters found, as possible candidates for dependencies.
    
    Returns:
    - A tuple of (var, details) where 'var' is the variable name and 'details' is a dictionary
      with keys:
          'relation' 
          'expression'
          'dependencies'
          
      or None if the line doesn't match.
    """
    pattern = r'(\w+)(?:\[\w+\])*\s*(=|~)\s*(.*?);'
    line = re.sub(r'\[\w+\]', '', line)
    match = re.match(pattern, line)
    if match:
        var, relation, expr = match.groups()
        dependencies = extract_dependencies(expr, defined_params)
        return var, {
            # 'label': var, 
            'relation': relation, 
            'expression': expr,
            'dependencies': dependencies
        }
    return None

def parse_dependencies(content, defined_params):
    """
    Parses the content of a block to find variable dependencies and distributions.
    Returns a dictionary where each key is a variable name and the value is
    a dictionary with 'distribution' and 'dependencies' keys.
    """
    dependencies = {}
    lines = content.splitlines()

    #print(defined_params)
    
    for line in lines:
        line = line.strip()

        # Try parsing line
        result = parse_line(line, defined_params)
        if result:
            var, details = result
            dependencies[var] = details

    return dependencies


def build_dependency_tree(blocks):
    """
    Builds a dependency tree from the parsed blocks.
    Returns a dictionary where each key is a variable name and the value is
    a dictionary with 'distribution' and 'dependencies' keys.
    """
    
    defined_params = set()
    for block_name, content in blocks.items():
        defd_ps = find_defined_parameters(content)
        #print(defd_ps)
        defined_params = defined_params.union(defd_ps)
        
    print(defined_params)
        
    dependency_tree = {}
    for block_name, content in blocks.items():
        block_dependencies = parse_dependencies(content, defined_params)
        dependency_tree.update(block_dependencies)
    
    return dependency_tree

def squish_out_variable(dependency_tree, var_to_eliminate):
    """
    Eliminates an intermediate variable from the dependency tree by
    redirecting its dependencies to the downstream variables.
    
    Parameters:
    - dependency_tree: The original dependency tree.
    - var_to_eliminate: The variable to be eliminated (squished out).
    
    Returns:
    - A modified dependency tree with the specified variable eliminated.
    """
    if var_to_eliminate not in dependency_tree:
        raise ValueError(f"Variable '{var_to_eliminate}' not found in the dependency tree.")
    
    # Get the dependencies of the variable to be eliminated
    inherited_deps = dependency_tree[var_to_eliminate]['dependencies']

    # Update dependencies of downstream variables
    new_dependency_tree = {}
    for var, details in dependency_tree.items():
        if var == var_to_eliminate:
            continue  # Skip the variable being eliminated
        
        updated_deps = [
            dep if dep != var_to_eliminate else inherited_deps
            for dep in details['dependencies']
        ]
        
        # Flatten the list and remove duplicates
        updated_deps = list(set(dep for sublist in updated_deps for dep in (sublist if isinstance(sublist, list) else [sublist])))

        new_dependency_tree[var] = dependency_tree[var]
        new_dependency_tree[var]['dependencies'] = updated_deps

       #  new_dependency_tree[var] = {
       #      'relation': details['relation'], 
       #      #'variable_type': details['variable_type'], 
       #      'expression': details['expression'],
       #      'dependencies': updated_deps
       #  }
    
    return new_dependency_tree

def parse_stan_file(file_path):
    with open(file_path, 'r') as file:
        content = file.read()
    
    # Remove comments and extract all blocks
    content = remove_comments(content)
    blocks = find_all_blocks(content)

    # Build the dependency tree
    dependency_tree = build_dependency_tree(blocks)
    
    return dependency_tree

def load_label_mappings(label_file):
    """
    Reads a label mapping file and returns a dictionary of mappings.
    The file should contain lines in the format: original_name new_label
    """
    label_mappings = {}
    with open(label_file, 'r') as file:
        for line in file:
            original, new_label = line.strip().split()
            label_mappings[original] = new_label
    return label_mappings

def render_dependency_tree(dependency_tree, label_mappings={}, verbose=False):
    """
    Renders a flat dependency tree using Graphviz.
    
    Parameters:
    - dependency_tree: The dictionary representing the dependency tree.
    
    Returns:
    - A Graphviz object representing the dependency tree.
    """
    dot = graphviz.Digraph()
    added_nodes = set()  # Set to track added nodes

    # Add nodes and edges to the graph
    for var, details in dependency_tree.items():

        # Apply label mapping if available
        var_label = label_mappings.get(var, var)
        # label = f"{var_label} ~ {distribution}" if distribution != 'None' else label
        
        # Create a node for each variable
        #variable_type = details['variable_type']
        # dot.node(var, label=label, shape='circle')
         # Determine the expression to show based on verbosity
        if verbose:
            expression = details['expression']
        else:
            # Only keep the distribution name if not verbose
            expression = details['expression'].split('(')[0]
        #expression = details['expression']
        relation = details['relation']
        spacer = "\n"*(relation=="~") + " "*(relation=="=")
        
        label = f"{var_label}{spacer}{relation}{spacer}{expression}" 
        
        # Add the node if it hasn't been added yet
        if var not in added_nodes:
            dot.node(var, label=label, shape='circle')
            added_nodes.add(var)
        # dot.node(var, label=label, shape='circle')

        
        # Create edges from dependencies to the variable
        for dep in details['dependencies']:
            if dep not in added_nodes:
                # Add the dependency node with the default options
                dep_label = label_mappings.get(dep, dep)
                dot.node(dep, label=dep_label, shape='circle')
                added_nodes.add(dep)

            dot.edge(dep, var)

    return dot



def main():
    parser = argparse.ArgumentParser(description='Visualize a Stan model.')
    parser.add_argument('-s', '--squish', nargs='*', type=str, help='Variable to squish out')
    parser.add_argument('-l', '--labels', type=str, help='Path to label mapping file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show full expressions in the dependency graph')
    parser.add_argument('stan_file', type=str, help='Path to the Stan model file')

    args = parser.parse_args()
    
    # print(args)
    # print(args.squish)

    dep_tree = parse_stan_file(args.stan_file)

    if args.labels:
        label_mappings = load_label_mappings(args.labels)
    else:
        label_mappings = {}

    print(label_mappings)

    if args.squish:
        for squish_var in args.squish:
            dep_tree = squish_out_variable(dep_tree, squish_var)

    dot = render_dependency_tree(dep_tree, label_mappings, verbose=args.verbose)
    dot.save('dependencies.dot')
    dot.render('dependencies', format='png', view=True, cleanup=True)
    # visualize_stan_model(args.stan_file)

if __name__ == '__main__':
    main()
