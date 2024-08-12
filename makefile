# Automatically find the notebook file and extract the base name (without extension)
NOTEBOOK_FILE := $(wildcard *.ipynb)
NOTEBOOK_NAME := $(basename $(NOTEBOOK_FILE))
PYTHON_SCRIPT := $(NOTEBOOK_NAME).py

# Define the main function as a multiline string
define MAIN_FUNCTION
def main():
    parser = argparse.ArgumentParser(description='Visualize a Stan model.')
    parser.add_argument('stan_file', type=str, help='Path to the Stan model file')
    args = parser.parse_args()

    visualize_stan_model(args.stan_file)

if __name__ == '__main__':
    main()
endef

export MAIN_FUNCTION

# Rule to convert the notebook to a Python script
$(PYTHON_SCRIPT): $(NOTEBOOK_FILE)
	jupyter nbconvert --to script $(NOTEBOOK_FILE) \
		--TemplateExporter.exclude_markdown=True \
		--TemplateExporter.exclude_output_prompt=True \
		--TemplateExporter.exclude_input_prompt=True

# Rule to append the main function to the Python script
append_main_function: $(PYTHON_SCRIPT)
	echo "writing main-script functionallity to .py"
	echo "$$MAIN_FUNCTION" >> $(PYTHON_SCRIPT)

# Combine both tasks
all: $(PYTHON_SCRIPT) append_main_function

clean: 
	rm *.py
	echo "removed .py scripts"

.PHONY: append_main_function clean
