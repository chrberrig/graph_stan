import re
import graphviz
import argparse

def parse_stan_model(file_path):
    with open(file_path, 'r') as file:
        content = file.read()

    # Regular expressions to capture different blocks
    data_block = re.search(r'data \{(.*?)\}', content, re.DOTALL)
    parameters_block = re.search(r'parameters \{(.*?)\}', content, re.DOTALL)
    model_block = re.search(r'model \{(.*?)\}', content, re.DOTALL)

    return data_block.group(1) if data_block else '', parameters_block.group(1) if parameters_block else '', model_block.group(1) if model_block else ''

def create_graph(data_block, parameters_block, model_block):
    dot = graphviz.Digraph()

    data_vars = []
    param_vars = []
    
    # Add nodes for data block
    if data_block:
        data_vars = re.findall(r'\b(int|real|vector|array)<[^>]*> (\w+)', data_block)
        for var_type, var_name in data_vars:
            dot.node(var_name, var_name)

    # Add nodes for parameters block
    if parameters_block:
        param_vars = re.findall(r'\b(real|vector|array)<[^>]*> (\w+)', parameters_block)
        for var_type, var_name in param_vars:
            dot.node(var_name, var_name)

    # Add edges for model block
    if model_block:
        model_vars = re.findall(r'(\w+) ~ (.*?);', model_block)
        for var, dist in model_vars:
            node_label = f'{var} ~ {dist}'
            dot.node(var, node_label)
            dependencies = re.findall(r'\b(\w+)\b', dist)
            for dep in dependencies:
                if dep != var and dep in [v[1] for v in data_vars + param_vars]:
                    dot.edge(dep, var)

    return dot

def visualize_stan_model(file_path):
    data_block, parameters_block, model_block = parse_stan_model(file_path)
    dot = create_graph(data_block, parameters_block, model_block)
    dot.render('stan_model', format='png', view=True)

def main():
    parser = argparse.ArgumentParser(description='Visualize a Stan model.')
    parser.add_argument('stan_file', type=str, help='Path to the Stan model file')
    args = parser.parse_args()

    visualize_stan_model(args.stan_file)

if __name__ == '__main__':
    main()
