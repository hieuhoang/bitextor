
BITEXTOR=/home/hieu/workspace/github/paracrawl/bitextor.hieu.malign

xzcat www.elenacaffe1863.com.xz | $BITEXTOR/targeted-crawl/import-mysql.py --out-dir out --lang1 fr --lang2 en
#xzcat www.samsonite.be.xz | $BITEXTOR/targeted-crawl/import-mysql.py --out-dir out --lang1 nl --lang2 en
#xzcat www.bizerba.com.xz | ./import-mysql.py --out-dir out

#xzcat www.samsonite.be.xz | $BITEXTOR/bitextor-warc2preprocess.py --output-dir out --lang1 en --lang2 fr

#$BITEXTOR/targeted-crawl/translate.py --dir out --lang nl