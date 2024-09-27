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
    type_pattern = r'(\b(int|real|vector|matrix|array)\b(?:<.*?>)?(?:\[[^\]]*\])?\s+)+(\w+)'
    #type_pattern = r'\b(int|real|vector|matrix|array)\b(?:<.*?>)?(?:\[[^\]]*\])?\s+(\w+)'
    
    defined_parameters = set()

    # Split content into lines and search for matches
    lines = content.splitlines()
    for line in lines:
        line = line.strip()

        # Find matches for the types
        match = re.search(type_pattern, line)
        if match:
            param_name = match.groups()[-1]  # The variable name is captured in the second group
            defined_parameters.add(param_name)

    return defined_parameters

def find_all_blocks(content):
    blocks = {}
    # block_pattern = r'(\w+)\s*\{'
    block_pattern = r'(\w+(?:\s+\w+)*)\s*\{'
    matches = re.finditer(block_pattern, content)

    for match in matches:
        block_name = match.group(1).strip()
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
    dependencies = list(set([dep for dep in candidates if dep in defined_params]))
    
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

    for line in lines:
        line = line.strip()

        # Try parsing line
        result = parse_line(line, defined_params)
        if result:
            var, details = result
            dependencies[var] = details

    return dependencies


def build_dependency_tree(blocks, verbose=False):
    """
    Builds a dependency tree from the parsed blocks.
    Returns a dictionary where each key is a variable name and the value is
    a dictionary with 'distribution' and 'dependencies' keys.
    """
    
    defined_params = set()
    print("Defined parameters: ")
    for block_name, content in blocks.items():
        defd_ps = find_defined_parameters(content)
        if verbose:
            print(block_name, defd_ps, "\n")
        defined_params = defined_params.union(defd_ps)
        
    if verbose:
        print("Defined parameters (all blocks):", defined_params, "\n")
        print("--"*20 + "\n")
        
    dependency_tree = {}
    for block_name, content in blocks.items():
        block_dependencies = parse_dependencies(content, defined_params)
        if verbose:
            print(block_name)
            for var_name, details in block_dependencies.items():
                print(" "*4+ var_name)
                for k, v in details.items():
                    print(" "*8 + f"{k}: {v}")
        dependency_tree.update(block_dependencies)
    
    if verbose:
        print("--"*20 + "\n")
        
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

def parse_stan_file(file_path, verbose=False):
    with open(file_path, 'r') as file:
        content = file.read()
    
    # Remove comments and extract all blocks
    content = remove_comments(content)
    blocks = find_all_blocks(content)

    # Build the dependency tree
    dependency_tree = build_dependency_tree(blocks, verbose=verbose)
    
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


import graphviz

def render_node(dot, var, details, label_mappings, added_nodes, explicit):
    """
    Renders a single node and its label based on its details.

    Parameters:
    - dot: The Graphviz Digraph object.
    - var: The variable name.
    - details: The details dictionary for the variable.
    - label_mappings: A dictionary for custom label mappings.
    - added_nodes: A set to track already added nodes.
    - explicit: Boolean indicating whether to show explicit expressions.
    """
    if var in added_nodes:
        return  # Node already rendered, no need to add again

    var_label = label_mappings.get(var, var)

    #if explicit:
    #    expression = details['expression']
    #else:
    #    expression = details['expression'].split('(')[0]
    
    expression = details['expression']
    if not explicit:
        expression = expression.split('(')[0]

    relation = details['relation']
    spacer = "\n" * (relation == "~") + " " * (relation == "=")

    label = f"{var_label}{spacer}{relation}{spacer}{expression}"

    dot.node(var, label=label, shape='circle')
    added_nodes.add(var)

def render_dependency_tree(dependency_tree, label_mappings={}, explicit=False, verbose=False):
    """
    Renders a dependency tree using Graphviz.

    Parameters:
    - dependency_tree: The dictionary representing the dependency tree.
    - label_mappings: A dictionary for custom label mappings.
    - explicit: Boolean indicating whether to show explicit expressions.
    - verbose: Boolean indicating whether to print verbose output.

    Returns:
    - A Graphviz object representing the dependency tree.
    """
    dot = graphviz.Digraph(graph_attr={'splines': 'false'})
    added_nodes = set()  # Set to track added nodes

    def render_dependencies(var):
        if var not in dependency_tree:
            return  # Base case: no more dependencies

        details = dependency_tree[var]

        # Render the node
        render_node(dot, var, details, label_mappings, added_nodes, explicit)

        # Render all dependencies of this node recursively
        for dep in details['dependencies']:
            if dep not in added_nodes:
                render_dependencies(dep)
            dot.edge(dep, var)

    for var in dependency_tree:
        if var not in added_nodes:
            render_dependencies(var)

    return dot



def main():
    parser = argparse.ArgumentParser(description='visualize a stan model.')
    parser.add_argument('-s', '--squish', nargs='*', type=str, help='variable to squish out')
    parser.add_argument('-l', '--labels', type=str, help='path to label mapping file')
    parser.add_argument('-e', '--explicit', action='store_true', help='show full expressions in the dependency graph')
    parser.add_argument('-v', '--verbose', action='store_true', help='show verbose output of stan-file parsing')
    parser.add_argument('-o', '--output', type=str, help='specify the base name for the output files (without extension)')
    # parser.add_argument('--format', type=str, choices=['graphviz', 'tikz'], default='graphviz', help='output format: graphviz or tikz')
    parser.add_argument('stan_file', type=str, help='path to the stan model file')

    args = parser.parse_args()
    
    dep_tree = parse_stan_file(args.stan_file, verbose=args.verbose)

    if args.labels:
        label_mappings = load_label_mappings(args.labels)
    else:
        label_mappings = {}

    # print(label_mappings)

    if args.squish:
        for squish_var in args.squish:
            dep_tree = squish_out_variable(dep_tree, squish_var)

    # if args.format == "graphviz":
    dot = render_dependency_tree(dep_tree, label_mappings, explicit=args.explicit)
    
    # Determine the output filename base
    output_base = args.output if args.output else 'dependencies'

    # Save the .dot file with the specified output name
    dot.save(f'{output_base}.dot')

    # Render the graph to a .png file with the specified output name
    dot.render(f'{output_base}', format='png', cleanup=False)

    dot.save('dependencies.dot')

    dot.render('dependencies', format='png', view=True, cleanup=True)


    # elif args.format == 'tikz':
    #     tikz_code = render_dependency_tree_tikz(dep_tree, label_mappings, explicit=args.explicit)
    #     
    #     # Output TikZ code to a .tex file
    #     output_base = args.output if args.output else 'dependencies'
    #     with open(f'{output_base}.tex', 'w') as file:
    #         file.write(tikz_code)

if __name__ == '__main__':
    main()
