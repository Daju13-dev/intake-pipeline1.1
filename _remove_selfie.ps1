$path = "C:\Users\Project\Desktop\ai-safety-campaign\pitch cardex.html"
$c = Get-Content -Raw $path
$pattern = "\s*<div class=\"pt-1 text-center\">\s*<label class=\"block text-xs font-bold text-ink-700 mb-1\">Upload Your Selfie<\/label>\s*<input data-file=\"m[0-9]_selfie_[0-9]\" type=\"file\" accept=\"image\/\*\" capture=\"user\" class=\"w-full text-sm border border-ink-200 rounded-xl p-2 bg-ink-50\"\/?\>\s*<\/div>\s*"
$c = [regex]::Replace($c, $pattern, "", [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
Set-Content $path $c
