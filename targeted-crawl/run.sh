#!/usr/bin/env bash

BITEXTOR=/home/hieu/workspace/github/paracrawl/bitextor.hieu.targeted

xzcat www.visitbritain.com.xz | $BITEXTOR/targeted-crawl/import-mysql.py --out-dir out --langs fr,en
#xzcat vade-retro.fr.xz | $BITEXTOR/targeted-crawl/import-mysql.py --out-dir out --lang fr,en &
#xzcat www.elenacaffe1863.com.xz | $BITEXTOR/targeted-crawl/import-mysql.py --out-dir out --langs fr,en
#xzcat www.samsonite.be.xz | $BITEXTOR/targeted-crawl/import-mysql.py --out-dir out --lang1 nl --lang2 en &
#xzcat www.bizerba.com.xz | ./import-mysql.py --out-dir out

#xzcat www.samsonite.be.xz | $BITEXTOR/bitextor-warc2preprocess.py --output-dir out --lang1 en --lang2 fr

wait

#cat fr-en.customMT.matches | ./import-doc-align.py --lang1 fr --lang2 en
#./create-graph.py --out-file a.dot --lang1 fr --lang2 en --root-page www.elenacaffe1863.com/index_fra.htm
#./create-graph.py --out-file a.dot --lang1 fr --lang2 en --root-page vade-retro.fr/
