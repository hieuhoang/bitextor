#!/usr/bin/env python3
import os
import sys
import numpy as np
import argparse
import hashlib
import tensorflow as tf
from tldextract import extract
import matplotlib
matplotlib.use('Agg')
import pylab as plt

relDir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
#print("relDir", relDir)
sys.path.append(relDir)
from common import GetLanguages, Languages, Timer
from helpers import GetEnvs, GetVistedSiblings, GetMatchedSiblings, NumParallelDocs, Env, Link
from corpus import Corpus
from neural_net import Qnets, Qnetwork, NeuralWalk, GetNextState
from candidate import Candidates, GetLangsVisited
from other_strategies import dumb, randomCrawl, balanced

######################################################################################
class LearningParams:
    def __init__(self, languages, saveDir, saveDirPlots, deleteDuplicateTransitions, langPair, maxLangId, defaultLang):
        self.gamma = 1.0 #0.999
        self.lrn_rate = 0.001
        self.alpha = 0.7
        self.max_epochs = 100001
        self.eps = 0.1
        self.maxBatchSize = 32
        self.minCorpusSize = 200
        self.overSampling = 1
        
        self.debug = False
        self.walk = 10
        self.NUM_ACTIONS = 30
        self.FEATURES_PER_ACTION = 1

        self.saveDir = saveDir
        self.saveDirPlots = saveDirPlots

        self.deleteDuplicateTransitions = deleteDuplicateTransitions
        
        self.reward = 100.0 #17.0
        self.cost = -1.0
        self.unusedActionCost = 0.0 #-555.0
        self.maxDocs = 500 #9999999999

        self.maxLangId = maxLangId
        self.defaultLang = defaultLang
        self.MAX_NODES = 1000

        langPairList = langPair.split(",")
        assert(len(langPairList) == 2)
        self.langIds = np.empty([1,2], dtype=np.int32)
        self.langIds[0,0] = languages.GetLang(langPairList[0])
        self.langIds[0,1] = languages.GetLang(langPairList[1])
        #print("self.langs", self.langs)

######################################################################################
def RunRLSavePlots(sess, qns, params, envs, saveDirPlots, epoch, sset):
    for env in envs:
        RunRLSavePlot(sess, qns, params, env, saveDirPlots, epoch, sset)

def RunRLSavePlot(sess, qn, params, env, saveDirPlots, epoch, sset):
    arrRL, totReward, totDiscountedReward = Trajectory(env, params, sess, qn, True)
    SavePlot(params, env, saveDirPlots, epoch, sset, arrRL, totReward, totDiscountedReward)

######################################################################################
def SavePlot(params, env, saveDirPlots, epoch, sset, arrRL, totReward, totDiscountedReward):
    arrDumb = dumb(env, params.maxDocs, params)
    arrRandom = randomCrawl(env, params.maxDocs, params)
    arrBalanced = balanced(env, params.maxDocs, params)
    #print("arrRL", len(arrRL))

    url = env.rootURL
    domain = extract(url).domain

    warmUp = 0 #200
    avgRandom = avgBalanced = avgRL = 0.0
    for i in range(params.maxDocs):
        if i > warmUp and arrDumb[i] > 0:
            avgRandom += arrRandom[i] / arrDumb[i]
            avgBalanced += arrBalanced[i] / arrDumb[i]
            avgRL += arrRL[i] / arrDumb[i]

    avgRandom = avgRandom / (len(arrRL) - warmUp)
    avgBalanced = avgBalanced / (len(arrRL) - warmUp)
    avgRL = avgRL / (len(arrRL) - warmUp)

    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    ax.plot(arrDumb, label="dumb ", color='maroon')
    ax.plot(arrRandom, label="random {0:.1f}".format(avgRandom), color='firebrick')
    ax.plot(arrBalanced, label="balanced {0:.1f}".format(avgBalanced), color='red')
    ax.plot(arrRL, label="RL {0:.1f} {1:.1f}".format(avgRL, totDiscountedReward), color='salmon')

    ax.legend(loc='upper left')
    plt.xlabel('#crawled')
    plt.ylabel('#found')
    plt.title("{sset} {domain}".format(sset=sset, domain=domain))

    fig.savefig("{dir}/{sset}-{domain}-{epoch}.png".format(dir=saveDirPlots, sset=sset, domain=domain, epoch=epoch))
    fig.show()

######################################################################################
class Transition:
    def __init__(self, env, action, link, langIds, targetQ, visited, candidates, nextVisited, nextCandidates):
        self.action = action
        self.link = link

        self.nextVisited = nextVisited.copy()
        self.nextCandidates = nextCandidates.copy()

        if candidates is not None:
            self.candidates = candidates.copy()
            numActions, linkLang, mask, numSiblings, numVisitedSiblings, numMatchedSiblings = candidates.GetFeatures()
            self.numActions = numActions
            self.linkLang = np.array(linkLang, copy=True) 
            self.mask = np.array(mask, copy=True) 
            self.numSiblings = np.array(numSiblings, copy=True) 
            self.numVisitedSiblings = np.array(numVisitedSiblings, copy=True) 
            self.numMatchedSiblings = np.array(numMatchedSiblings, copy=True) 
            self.langIds = langIds 
            self.targetQ = np.array(targetQ, copy=True)

        if visited is not None:
            self.visited = visited.copy()
            self.langsVisited = GetLangsVisited(visited, langIds, env)

    def Debug(self):
        ret = str(self.link.parentNode.urlId) + "->" + str(self.link.childNode.urlId) + " " + str(self.visited)
        return ret
    
######################################################################################
def Neural(env, params, prevTransition, sess, qnA, qnB):
    nextCandidates = prevTransition.nextCandidates.copy()
    nextVisited = prevTransition.nextVisited.copy()

    qValues, maxQ, action, link, reward = NeuralWalk(env, params, nextCandidates, nextVisited, sess, qnA)
    assert(link is not None)
    assert(qValues.shape[1] > 0)
    #print("qValues", qValues.shape, action, prevTransition.nextCandidates.Count(), nextCandidates.Count())

    # calc nextMaxQ
    if nextCandidates.Count() > 0:
        #  links to follow NEXT
        _, _, nextAction = qnA.PredictAll(env, sess, params.langIds, nextVisited, nextCandidates)
        #print("nextAction", nextAction, nextLangRequested, nextCandidates.Debug())
        nextQValuesB, _, _ = qnB.PredictAll(env, sess, params.langIds, nextVisited, nextCandidates)
        nextMaxQ = nextQValuesB[0, nextAction]
        #print("nextMaxQ", nextMaxQ, nextMaxQB, nextQValuesA[0, nextAction])
    else:
        nextMaxQ = 0

    newVal = reward + params.gamma * nextMaxQ
    targetQ = (1 - params.alpha) * maxQ + params.alpha * newVal
    qValues[0, action] = targetQ

    transition = Transition(env,
                            action, 
                            link,
                            params.langIds,
                            qValues,
                            prevTransition.nextVisited,
                            prevTransition.nextCandidates,
                            nextVisited,
                            nextCandidates)

    return transition, reward

######################################################################################
def Trajectory(env, params, sess, qns, test):
    ret = []
    totReward = 0.0
    totDiscountedReward = 0.0
    discount = 1.0

    startNode = env.nodes[sys.maxsize]

    nextVisited = set()
    nextVisited.add(startNode.urlId)

    nextCandidates = Candidates(params, env)
    nextCandidates.AddLinks(startNode, nextVisited, params)

    transition = Transition(env, -1, None, params.langIds, 0, None, None, nextVisited, nextCandidates)

    if test:
        mainStr = "lang:" + str(startNode.lang)
        rewardStr = "rewards:"
        actionStr = "actions:"

    while True:
        tmp = np.random.rand(1)
        if tmp > 0.5:
            qnA = qns.q[0]
            qnB = qns.q[1]
        else:
            qnA = qns.q[1]
            qnB = qns.q[0]

        transition, reward = Neural(env, params, transition, sess, qnA, qnB)
        #print("visited", transition.visited)
        #print("candidates", transition.candidates.Debug())
        #print("transition", transition.Debug())
        #print()

        numParallelDocs = NumParallelDocs(env, transition.visited)
        ret.append(numParallelDocs)

        totReward += reward
        totDiscountedReward += discount * reward
        discount *= params.gamma

        if test:
            mainStr += "->" + str(transition.link.childNode.lang)
            rewardStr += "->" + str(reward)
            actionStr += str(transition.action) + " "

            if transition.link.childNode.alignedNode is not None:
                mainStr += "*"
        else:
            tmp = np.random.rand(1)
            if tmp > 0.5:
                corpus = qnA.corpus
            else:
                corpus = qnB.corpus
            corpus.AddTransition(transition)

        if transition.nextCandidates.Count() == 0:
            break

        if len(transition.visited) >= params.maxDocs:
            break

    if test:
        mainStr += " " + str(len(ret)) 
        rewardStr += " " + str(totReward) + "/" + str(totDiscountedReward)
        print(actionStr)
        print(mainStr)
        print(rewardStr)

    return ret, totReward, totDiscountedReward

######################################################################################
def Train(params, sess, saver, qns, envs, envsTest):
    print("Start training")
    for epoch in range(params.max_epochs):
        print("epoch", epoch)
        for env in envs:
            TIMER.Start("Trajectory")
            arrRL, totReward, totDiscountedReward = Trajectory(env, params, sess, qns, False)
            TIMER.Pause("Trajectory")

            SavePlot(params, env, params.saveDirPlots, epoch, "train", arrRL, totReward, totDiscountedReward)

        TIMER.Start("Train")
        qns.q[0].corpus.Train(sess, params)
        qns.q[1].corpus.Train(sess, params)
        TIMER.Pause("Train")

        if epoch > 0 and epoch % params.walk == 0:
            #print("epoch", epoch)
            #SavePlots(sess, qns, params, envs, params.saveDirPlots, epoch, "train")
            RunRLSavePlots(sess, qns, params, envsTest, params.saveDirPlots, epoch, "test")

######################################################################################
def main():
    global TIMER
    TIMER = Timer()

    oparser = argparse.ArgumentParser(description="intelligent crawling with q-learning")
    oparser.add_argument("--config-file", dest="configFile", required=True,
                         help="Path to config file (containing MySQL login etc.)")
    oparser.add_argument("--language-pair", dest="langPair", required=True,
                         help="The 2 language we're interested in, separated by ,")
    oparser.add_argument("--save-dir", dest="saveDir", default=".",
                         help="Directory that model WIP are saved to. If existing model exists then load it")
    oparser.add_argument("--save-plots", dest="saveDirPlots", default="plot",
                     help="Directory ")
    oparser.add_argument("--delete-duplicate-transitions", dest="deleteDuplicateTransitions",
                         default=False, help="If True then only unique transition are used in each batch")
    oparser.add_argument("--num-train-hosts", dest="numTrainHosts", type=int,
                         default=1, help="Number of domains to train on")
    oparser.add_argument("--num-test-hosts", dest="numTestHosts", type=int,
                         default=3, help="Number of domains to test on")
    options = oparser.parse_args()

    np.random.seed()
    np.set_printoptions(formatter={'float': lambda x: "{0:0.1f}".format(x)}, linewidth=666)

    languages = GetLanguages(options.configFile)
    params = LearningParams(languages, options.saveDir, options.saveDirPlots, options.deleteDuplicateTransitions, options.langPair, languages.maxLangId, languages.GetLang("None"))

    if not os.path.exists(options.saveDirPlots): os.makedirs(options.saveDirPlots, exist_ok=True)

    print("options.numTrainHosts", options.numTrainHosts)
    #hosts = ["http://vade-retro.fr/"]
    hosts = ["http://www.buchmann.ch/", "http://telasmos.org/", "http://tagar.es/"]
    #hosts = ["http://www.visitbritain.com/"]

    #hostsTest = ["http://vade-retro.fr/"]
    #hostsTest = ["http://www.visitbritain.com/"]
    hostsTest = ["http://www.visitbritain.com/", "http://chopescollection.be/", "http://www.bedandbreakfast.eu/"]

    envs = GetEnvs(options.configFile, languages, hosts[:options.numTrainHosts])
    envsTest = GetEnvs(options.configFile, languages, hostsTest[:options.numTestHosts])

    tf.reset_default_graph()
    qns = Qnets(params)
    init = tf.global_variables_initializer()

    saver = None #tf.train.Saver()
    with tf.Session() as sess:
        sess.run(init)

        Train(params, sess, saver, qns, envs, envsTest)

######################################################################################
main()
