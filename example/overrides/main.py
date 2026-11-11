"""
To run: `buck2 run :main`
"""

import colorama
import cowsay

# :cowsay is the local replacement, not the wheel from the lock.
out = cowsay.get_output_string("cow", "hello")
assert out == "overridden cow: hello", out

# :colorama is the lock's wheel, passed through the fixup genrule.
colorama.init()
print(colorama.Fore.GREEN + out + colorama.Fore.RESET)
