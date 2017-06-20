from __future__ import print_function

import argparse
import collections
import json
import os

import numpy as np
import tensorflow as tf

from bayou.experiments.nonbayesian.utils import CHILD_EDGE, SIBLING_EDGE
from bayou.experiments.nonbayesian.model import Model
from bayou.experiments.nonbayesian.utils import read_config

MAX_GEN_UNTIL_STOP = 20


def infer(clargs):
    with tf.Session() as sess:
        predictor = NonBayesianPredictor(clargs.save, sess)
        err = 0
        asts = []
        if clargs.evidence_file:
            with open(clargs.evidence_file) as f:
                js = json.load(f)
        for c in range(clargs.n):
            print('Generated {} ASTs ({} errors)'.format(c, err), end='\r')
            try:
                ast = predictor.generate_ast(js)
                asts.append(ast)
                c += 1
            except AssertionError:
                err += 1

    if clargs.output_file is None:
        print(json.dumps({'asts': asts}, indent=2))
    else:
        with open(clargs.output_file, 'w') as f:
            json.dump({'asts': asts}, fp=f, indent=2)
    print('Number of errors: {}'.format(err))


class NonBayesianPredictor(object):

    def __init__(self, save, sess):
        self.sess = sess

        # load the saved config
        with open(os.path.join(save, 'config.json')) as f:
            config = read_config(json.load(f), save_dir=save, infer=True)
        self.model = Model(config, True)

        # restore the saved model
        tf.global_variables_initializer().run()
        saver = tf.train.Saver(tf.global_variables())
        ckpt = tf.train.get_checkpoint_state(save)
        saver.restore(self.sess, ckpt.model_checkpoint_path)

    def infer(self, evidences):
        encoding = self.encoding_from_evidence(evidences)
        return self.generate_ast(encoding)

    def encoding_from_evidence(self, js_evidences):
        return self.model.infer_encoding(self.sess, js_evidences)

    def gen_until_STOP(self, evidences, in_nodes, in_edges, check_call=False):
        ast = []
        nodes, edges = in_nodes[:], in_edges[:]
        num = 0
        while True:
            assert num < MAX_GEN_UNTIL_STOP # exception caught in main
            dist = self.model.infer_ast(self.sess, evidences, nodes, edges)
            idx = np.random.choice(range(len(dist)), p=dist)
            prediction = self.model.config.decoder.chars[idx]
            nodes += [prediction]
            if check_call:  # exception caught in main
                assert prediction not in ['DBranch', 'DExcept', 'DLoop', 'DSubTree']
            if prediction == 'STOP':
                edges += [SIBLING_EDGE]
                break
            js = self.generate_ast(evidences, nodes, edges + [CHILD_EDGE])
            ast.append(js)
            edges += [SIBLING_EDGE]
            num += 1
        return ast, nodes, edges

    def generate_ast(self, evidences, in_nodes=['DSubTree'], in_edges=[CHILD_EDGE]):
        ast = collections.OrderedDict()
        node = in_nodes[-1]

        # Return the "AST" if the node is an API call
        if node not in ['DBranch', 'DExcept', 'DLoop', 'DSubTree']:
            ast['node'] = 'DAPICall'
            ast['_call'] = node
            return ast

        ast['node'] = node
        nodes, edges = in_nodes[:], in_edges[:]

        if node == 'DBranch':
            ast_cond, nodes, edges = self.gen_until_STOP(evidences, nodes, edges, check_call=True)
            ast_then, nodes, edges = self.gen_until_STOP(evidences, nodes, edges)
            ast_else, nodes, edges = self.gen_until_STOP(evidences, nodes, edges)
            ast['_cond'] = ast_cond
            ast['_then'] = ast_then
            ast['_else'] = ast_else
            return ast

        if node == 'DExcept':
            ast_try, nodes, edges = self.gen_until_STOP(evidences, nodes, edges)
            ast_catch, nodes, edges = self.gen_until_STOP(evidences, nodes, edges)
            ast['_try'] = ast_try
            ast['_catch'] = ast_catch
            return ast

        if node == 'DLoop':
            ast_cond, nodes, edges = self.gen_until_STOP(evidences, nodes, edges, check_call=True)
            ast_body, nodes, edges = self.gen_until_STOP(evidences, nodes, edges)
            ast['_cond'] = ast_cond
            ast['_body'] = ast_body
            return ast

        if node == 'DSubTree':
            ast_nodes, _, _ = self.gen_until_STOP(evidences, nodes, edges)
            ast['_nodes'] = ast_nodes
            return ast


def find_api(nodes):
    for node in nodes:
        if node['node'] == 'DAPICall':
            call = node['_call'].split('.')
            api = '.'.join(call[:3])
            return api
    return None


def plot2d(asts):
    import matplotlib.pyplot as plt
    import matplotlib.cm as cm
    dic = {}
    for ast in asts:
        sample = ast['psi']
        api = find_api(ast['_nodes'])
        if api is None:
            continue
        if api not in dic:
            dic[api] = []
        dic[api].append(sample)

    apis = dic.keys()
    colors = cm.rainbow(np.linspace(0, 1, len(dic)))
    plotpoints = []
    for api, color in zip(apis, colors):
        x = list(map(lambda s: s[0], dic[api]))
        y = list(map(lambda s: s[1], dic[api]))
        plotpoints.append(plt.scatter(x, y, color=color))

    plt.legend(plotpoints, apis, scatterpoints=1, loc='lower left', ncol=3, fontsize=8)
    plt.axhline(0, color='black')
    plt.axvline(0, color='black')
    plt.show()
        
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--save', type=str, default='save',
                        help='directory to laod model from')
    parser.add_argument('--evidence_file', type=str, default=None,
                        help='input file containing evidences (in JSON)')
    parser.add_argument('--output_file', type=str, default=None,
                        help='file to print AST (in JSON) to')
    parser.add_argument('--n', type=int, default=1,
                        help='number of ASTs to sample/synthesize')

    clargs = parser.parse_args()
    if not clargs.evidence_file and not clargs.random:
        parser.error('Provide at least one option: --evidence_file or --random')
    if clargs.plot2d and not clargs.random:
        parser.error('--plot2d requires --random (otherwise there is only one psi to plot)')
    infer(clargs)