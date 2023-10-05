import subprocess

def replace_file_line(file, old_line_text, new_line_text):
    """Replace a line in a file

    Args:
        file (file obj): File where a line should be replaced
        old_line_text (str): Text in the line that should be replaced
        new_line_text (str): New Text
    """

    with open(file, "r") as f:
        contents = f.readlines()

        # allow graceful termination if line to replace is missing
        try:
            l_idx = contents.index(old_line_text)
        except ValueError:
            return

        contents[l_idx] = new_line_text

    with open(file, "w") as f:
        contents = "".join(contents)
        f.write(contents)

def compile_dts(src, dest, *args):
    """ Invokes dts to compile a .dts to .dtb
    Args:
        src (str): Path to source file
        dest (str): Path to output file
    """

    subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", dest, src, *args], check=True)
