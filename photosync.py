#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

import gi
import sys
import re
import os
import datetime
import time
import getopt
import logging
import math
import shutil
import subprocess

from lxml import etree as ET
from glob import glob
from threading import Thread
from distutils import spawn
from __builtin__ import str

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

from gi.repository import Gdk, Gtk, GObject, GLib


class VideoEncodeProgressDialog(Gtk.Dialog):
    """
    Dialog utilizada para exibir o progresso da conversão de vídeos
    """
    
    total = 0
    completedSize = 0
    mustStop = False
    failed = False

    def __init__(self, parent, arquivos, destino):
        Gtk.Dialog.__init__(self, "Compactando vídeos ", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL))

        self.set_size_request(250, 150)
        self.set_border_width(10)

        self.listaArquivos = arquivos
        self.dirDestino = destino

        # Container principal
        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(4)
        grid.set_row_spacing(6)

        for arquivo in self.listaArquivos:
            self.total = self.total + os.stat(arquivo).st_size

        # Label com o título da atividade
        grid.attach(Gtk.Label(label="Efetuando a re-codificação de " + str(len(arquivos)) + 
                              " arquivos (" + to_human_size(self.total) + ")", halign=Gtk.Align.START), 0, 0, 6, 1)

        # Progresso total
        self.progressBarTotal = Gtk.ProgressBar(show_text=True)
        grid.attach(self.progressBarTotal, 0, 1, 6, 1)

        # Titulo de info do progresso global
        self.labelProgressTotal = Gtk.Label(halign=Gtk.Align.START)
        grid.attach(self.labelProgressTotal, 0, 2, 6, 1)

        # Progresso da conversão do arquivo
        self.progressbarAtual = Gtk.ProgressBar(show_text=True)
        grid.attach(self.progressbarAtual, 0, 3, 6, 1)

        # Titulo do arquivo
        self.labelAtual = Gtk.Label(halign=Gtk.Align.START)
        grid.attach(self.labelAtual, 0, 4, 6, 1)

        self.get_content_area().pack_start(grid, True, True, 0)
        self.show_all()

        # Inicia a threa de conversão de vídeos
        thread = Thread(target=self.processa_videos)
        thread.daemon = True
        thread.start()

    def update_progess(self, tituloBarraTotal, progressoTotal, tituloLabelTotal, tituloLabelAtual):
        """        
        Atualiza os contadores do arquivo atual e progresso total
        """
        
        self.progressBarTotal.set_text(tituloBarraTotal)
        self.progressBarTotal.set_fraction(progressoTotal)  # O processo deve ser entre 0.0 e 1.0
        self.labelProgressTotal.set_text(tituloLabelTotal)
        self.labelAtual.set_text(tituloLabelAtual)

        return False

    def update_progess_arquivo(self, progressoConversao):
        """
        Atualiza o progress bar da conversão do arquivo
        """
        
        self.progressbarAtual.set_fraction(progressoConversao)  # O processo deve ser entre 0.0 e 1.0
        return False

    def processa_videos(self):
        """
        Efetua a conversão dos videos
        """
        
        DURATION = "Duration:"
        FRAME = "frame="
        TIME = "time="

        # Recupera o codec e o path do ffmpeg
        codecIdx = get_app_settings("codec_video")
        codecIdx = codecIdx if codecIdx is not None else "0"
        codecInfo = get_codec_info(CODECS_VIDEO[int(codecIdx)])

        for arquivo in self.listaArquivos:
            try:

                if not os.path.isfile(arquivo):
                    debug("Ignorando aquivo inexistente: " + arquivo)
                    self.failed = True
                    continue

                self.completedSize = self.completedSize + os.stat(arquivo).st_size
                novoArquivo = self.dirDestino + os.sep + get_destino_arquivo(arquivo)
                arquivoCopia = self.dirDestino + os.sep + os.path.basename(arquivo)

                # Monta os parâmetros para a criação do novo video, de acordo com o codec escolhido
                args = [get_caminho_ffmpeg(), "-hide_banner", "-i", arquivoCopia]
                args.extend(codecInfo["params"])
                novoArquivo = novoArquivo[:novoArquivo.rindex('.')] + codecInfo["sufixo"]
                args.append(novoArquivo)

                # Estatísticas da conversão total
                tituloBarraTotal = "[" + to_human_size(self.completedSize) + "/" + to_human_size(self.total) + "]"
                tituloLabelTotal = "Original: " + os.path.basename(arquivo) + " (" + to_human_size(os.stat(arquivo).st_size) + ")"

                if os.path.isfile(novoArquivo):
                    tituloLabelAtual = "Compactado: " + os.path.basename(novoArquivo)
                else:
                    tituloLabelAtual = "Compactado: <Falha ao ler os dados do arquivo>"

                progressoTotal = self.completedSize / self.total  # Percentual do progresso

                # Atualiza as estatíticas do total e o nome do arquivo de destino
                GLib.idle_add(self.update_progess, tituloBarraTotal, progressoTotal, tituloLabelTotal, tituloLabelAtual)

                # Cria o diretório, se não existir
                directory = os.path.dirname(novoArquivo)
                if not os.path.exists(directory):
                    debug("Criando o diretório " + directory)
                    os.makedirs(directory)

                # Verifica se o vídeo de destino existe
                if os.path.isfile(novoArquivo):
                    debug("Removendo arquivo de destino existente: " + novoArquivo)
                    os.remove(novoArquivo)

                maxSecs = 0
                curSecs = 0

                # Checa se o usuário interrrompeu a conversão
                if self.mustStop:
                    return None

                # Efetua a conversão do arquivo de video
                debug("Executando aplicação: " + str(args))

                global gProcessoFfmpeg
                gProcessoFfmpeg = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

                # Inicia o processo e itera entre as linhas recebidas no stdout
                for line in iter(gProcessoFfmpeg.stdout.readline, ''):
                    if DURATION in line:
                        # Essa linha contém o tamanho total do vídeo
                        try:
                            tmp = line[line.find(DURATION):]
                            tmp = tmp[tmp.find(" ") + 1:]
                            tmp = tmp[0: tmp.find(".")]
                            x = time.strptime(tmp, '%H:%M:%S')
                            maxSecs = datetime.timedelta(hours=x.tm_hour, minutes=x.tm_min, seconds=x.tm_sec).total_seconds()
                        except ValueError:
                            debug("Falha ao converter o horário: " + tmp)

                    elif line.startswith(FRAME) and TIME in line:
                        try:
                            # Captura o tempo da conversão (timestamp)
                            tmp = line[line.find(TIME):]
                            tmp = tmp[tmp.find("=") + 1: tmp.find(".")]
                            x = time.strptime(tmp, '%H:%M:%S')
                            curSecs = datetime.timedelta(hours=x.tm_hour, minutes=x.tm_min, seconds=x.tm_sec).total_seconds()
                        except ValueError:
                            debug("Falha ao converter o horário: " + tmp)

                    # Atualiza o progresso da conversão do arquivo de destino
                    if curSecs > 0 and maxSecs > 0:
                        GLib.idle_add(self.update_progess_arquivo, curSecs / maxSecs)

                # Finaliza o processo do ffmpeg
                gProcessoFfmpeg.stdout.close()
                gProcessoFfmpeg.wait()

                if os.path.isfile(arquivo):
                    debug("Vídeo original: " + arquivo + " (" + to_human_size(os.stat(arquivo).st_size) + ")")

                if os.path.isfile(novoArquivo):
                    debug("Vídeo convertido: " + novoArquivo + " (" + to_human_size(os.stat(novoArquivo).st_size) + ")")

                # Remove a cópia do video original
                if 'True' == get_app_settings("remover_video_apos_conversao"):
                    video_original = os.path.dirname(novoArquivo) + os.sep + os.path.basename(arquivo)
                    if os.path.isfile(video_original):
                        debug("Removendo a cópia do video original: " + video_original)
                        os.remove(video_original)

            except Exception as e:
                debug("Falha ao converter o arquivo de vídeo " + arquivo + " : ", str(e))
                self.failed = True

        self.close()


class FileCopyProgressDialog(Gtk.Dialog):
    """
    Dialog utilizada para exibir o progresso da cópia de arquivos
    """
    
    mustStop = False
    failed = False
    total = 0
    completedSize = 0

    def __init__(self, parent, arquivos, destino):
        Gtk.Dialog.__init__(self, "Copiando arquivos ", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL))

        self.set_size_request(250, 150)
        self.set_border_width(10)
        self.listaArquivos = arquivos
        self.dirDestino = destino

        # Container principal
        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(4)
        grid.set_row_spacing(6)

        for arquivo in self.listaArquivos:
            self.total = self.total + os.stat(arquivo).st_size

        # Label com o título da atividade
        grid.attach(Gtk.Label(label="Efetuando a cópia de " + str(len(arquivos)) + 
                              " arquivos (" + to_human_size(self.total) + ")", halign=Gtk.Align.START), 0, 0, 6, 1)

        # Barra de progresso global
        self.progress_bar = Gtk.ProgressBar(show_text=True)
        grid.attach(self.progress_bar, 0, 1, 6, 1)

        # Label do progresso do arquivo
        self.labelProgress = Gtk.Label(halign=Gtk.Align.START)
        grid.attach(self.labelProgress, 0, 2, 6, 1)

        self.get_content_area().pack_start(grid, True, True, 0)
        self.show_all()

        thread = Thread(target=self.copia_arquivos)
        thread.daemon = True
        thread.start()

    def update_progess(self, tituloProgresso, progressoCopia, tituloCopia):
        """
        Atualiza o progress bar da cópia dos arquivos 
        """
        self.progress_bar.set_fraction(progressoCopia)  # O processo deve ser entre 0.0 e 1.0
        self.progress_bar.set_text(tituloProgresso)
        self.labelProgress.set_text(tituloCopia)
        return False

    def copia_arquivos(self):
        """
        Efetua a cópia dos arquivos
        """
        totalArquivos = len(self.listaArquivos)
        for i, arquivo in enumerate(self.listaArquivos):
            try:
                self.completedSize = self.completedSize + os.stat(arquivo).st_size

                tituloProgresso = "[" + to_human_size(self.completedSize) + "/" + to_human_size(self.total) + "]"
                progressoCopia = self.completedSize / self.total  # Percentual do progresso
                tituloCopia = "[" + str(i) + "/" + str(totalArquivos) + "] " + os.path.basename(arquivo) + " (" + to_human_size(os.stat(arquivo).st_size) + ")"

                GLib.idle_add(self.update_progess, tituloProgresso, progressoCopia, tituloCopia)

                # Verifica se a cópia foi interrompida
                if self.mustStop:
                    return None

                # Cria o diretório, se não existir
                novoArquivo = self.dirDestino + os.sep + get_destino_arquivo(arquivo)
                dirNovoArquivo = os.path.dirname(novoArquivo)
                if not os.path.exists(dirNovoArquivo):
                    try:
                        debug("Criando o diretório " + dirNovoArquivo)
                        os.makedirs(dirNovoArquivo)
                    except Exception as e:
                        debug("Falha ao criar o diretório de destino [" + dirNovoArquivo + "]: " + str(e))
                        continue

                # Sempre copia o arquivo
                debug("Copiando " + arquivo + " -> " + novoArquivo)
                shutil.copy2(arquivo, novoArquivo)

                # Se selecionado a opção, remover após a cópia
                if 'True' == get_app_settings("remover_apos_copia"):
                    try:
                        debug("Removendo arquivo de origem " + arquivo)
                        os.remove(arquivo)
                    except Exception as e:
                        debug("Falha ao remover o arquivo de origem após a cópia [" + arquivo + "]: " + str(e))
            except Exception as e:
                debug("Falha durante a cópia do arquivo [" + arquivo + "]: " + str(e))
                continue

        self.close()


class InputDialog(Gtk.Dialog):
    """
    Dialog de solicitação de dados em um campo de texto ou combo
    """
    
    textField = None
    comboBox = None

    def __init__(self, parent, message, default, opcoes):
        Gtk.Dialog.__init__(self, "Solicitação de informação do usuário", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(350, 150)
        self.set_border_width(10)

        topbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        topbox.pack_start(Gtk.Label(label=message, halign=Gtk.Align.START), True, True, 0)

        debug("Solicitação de informção ao usuário: " + message)
        if opcoes is None:
            # Campo de texto
            self.textField = Gtk.Entry()
            self.textField.set_text(default)
            topbox.pack_start(self.textField, True, True, 0)
        else:
            self.comboBox = Gtk.ComboBoxText()
            # Campo de texto
            for i, word in enumerate(opcoes.split('|')):
                self.comboBox.append_text(word)
                if default and unicode(word) == unicode(default):
                    self.comboBox.set_active(i)

            topbox.pack_start(self.comboBox, True, True, 0)

        self.get_content_area().pack_start(topbox, False, False, 0)
        self.show_all()

    def do_valida_campos(self):
        if self.textField is not None and not self.textField.get_text().strip():
            return show_message('Campo obrigatório não informado:', 'É necessário especificar o valor do campo.')

        if self.comboBox is not None and not self.comboBox.get_active_text():
            return show_message('Campo obrigatório não informado:', 'É necessário selecionar um item.')

        return Gtk.ResponseType.OK

    def show_and_get_info(self):
        while self.run() == Gtk.ResponseType.OK:
            if self.do_valida_campos() is not None:
                if self.textField is not None:
                    resp = self.textField.get_text().strip()
                else:
                    resp = self.comboBox.get_active_text()
                self.destroy()
                return resp

        self.destroy()
        return None


class ConfigDialog(Gtk.Dialog):
    """
    Dialog de configuração da aplicação
    """
    
    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Configurações da aplicação", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(400, 300)
        self.set_border_width(10)

        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(2)
        grid.set_row_spacing(2)

        gridCheck = Gtk.Grid()

        # Apenas fotos e videos
        self.checkFotosVideos = Gtk.CheckButton("Copiar apenas as fotos e os vídeos")
        self.checkFotosVideos.set_active('True' == get_app_settings("apenas_fotos_e_videos"))
        gridCheck.attach(self.checkFotosVideos, 0, 0, 3, 1)

        # Sobrescrever
        self.checkSobrescrever = Gtk.CheckButton("Sobrescrever os arquivos de destino")
        self.checkSobrescrever.set_active('True' == get_app_settings("sobrescrever_arquivos"))
        gridCheck.attach(self.checkSobrescrever, 4, 0, 3, 1)

        # Remover após copia
        self.checkRemoverCopia = Gtk.CheckButton("Remover os arquivos originais após a cópia")
        self.checkRemoverCopia.set_active('True' == get_app_settings("remover_apos_copia"))
        gridCheck.attach(self.checkRemoverCopia, 0, 1, 3, 1)

        # Exibir resolução dos arquivos
        self.checkExibirResolucao = Gtk.CheckButton("Exibir a resolução dos arquivos")
        self.checkExibirResolucao.set_active('True' == get_app_settings("exibir_resolucao_arquivos"))
        gridCheck.attach(self.checkExibirResolucao, 4, 1, 3, 1)
        
        # Comprimir videos
        self.checkRecode = Gtk.CheckButton("Re-codificar arquivos de vídeo")
        self.checkRecode.set_active('True' == get_app_settings("recodificar_videos"))
        gridCheck.attach(self.checkRecode, 0, 2, 3, 1)

        # Formato do video
        flowbox = Gtk.FlowBox()

        flowbox.add(Gtk.Label(label="Formato do vídeo:", halign=Gtk.Align.START))
        self.comboCodecs = Gtk.ComboBoxText()
        
        for codec in CODECS_VIDEO:
            self.comboCodecs.append_text(codec)
            
        self.comboCodecs.set_active(0)
        self.comboCodecs.set_entry_text_column(1)
        codec_idx = get_app_settings("codec_video")
        if codec_idx is not None:
            self.comboCodecs.set_active(int(codec_idx))
            
        flowbox.add(self.comboCodecs)

        gridCheck.attach(flowbox, 4, 2, 3, 1)

        # Remover Videos convertidos
        self.checkRemoverVideo = Gtk.CheckButton("Remover a cópia do video original após a conversão")
        self.checkRemoverVideo.set_active('True' == get_app_settings("remover_video_apos_conversao"))
        gridCheck.attach(self.checkRemoverVideo, 0, 3, 3, 1)

        grid.attach(gridCheck, 0, 0, 6, 3)

        # Campo Destino

        self.editCaminhoFfmpeg = Gtk.Entry()
        self.editCaminhoFfmpeg.set_text(get_app_settings("caminho_ffmpeg"))

        button = Gtk.Button.new_from_icon_name("document-open", Gtk.IconSize.BUTTON)
        button.connect("clicked", self.do_click_seleciona_ffmpeg)

        boxDestino = Gtk.Box()
        boxDestino.pack_start(Gtk.Label(label="Caminho do ffmpeg:", halign=Gtk.Align.START), False, False, 0)
        boxDestino.pack_start(self.editCaminhoFfmpeg, True, True, 4)
        boxDestino.pack_end(button, False, False, 0)

        grid.attach(boxDestino, 0, 3, 6, 1)

        # Lista de videos
        self.taskstoreVideos = Gtk.ListStore(str)
        self.treeviewVideos = Gtk.TreeView(model=self.taskstoreVideos)
        self.treeviewVideos.append_column(Gtk.TreeViewColumn("Extensão dos arquivos de Video", Gtk.CellRendererText(), text=0))

        scrollableTreelistVideos = Gtk.ScrolledWindow()
        scrollableTreelistVideos.set_vexpand(True)
        scrollableTreelistVideos.set_hexpand(True)
        scrollableTreelistVideos.add(self.treeviewVideos)

        gridVideo = Gtk.Grid()
        gridVideo.attach(scrollableTreelistVideos, 0, 0, 6, 6)

        for video in get_app_settings("extensoes_video").split('|'):
            self.taskstoreVideos.append([video])

        flowbox = Gtk.FlowBox()
        button = Gtk.Button.new_from_icon_name("list-add", Gtk.IconSize.MENU)
        button.connect("clicked", self.do_click_add_video)
        flowbox.add(button)
        gridVideo.attach(flowbox, 7, 3, 1, 1)

        flowbox = Gtk.FlowBox()
        button = Gtk.Button.new_from_icon_name("list-remove", Gtk.IconSize.MENU)
        button.connect("clicked", self.do_click_del_video)
        flowbox.add(button)
        gridVideo.attach(flowbox, 7, 4, 1, 1)

        grid.attach(gridVideo, 0, 4, 3, 6)

        # Lista de Fotos
        self.taskstoreFotos = Gtk.ListStore(str)
        self.treeviewFotos = Gtk.TreeView(model=self.taskstoreFotos)
        self.treeviewFotos.append_column(Gtk.TreeViewColumn("Extensão dos arquivos de Foto", Gtk.CellRendererText(), text=0))

        scrollableTreelistFotos = Gtk.ScrolledWindow()
        scrollableTreelistFotos.set_vexpand(True)
        scrollableTreelistFotos.set_hexpand(True)
        scrollableTreelistFotos.add(self.treeviewFotos)

        gridFoto = Gtk.Grid()
        gridFoto.attach(scrollableTreelistFotos, 0, 0, 6, 6)

        for foto in get_app_settings("extensoes_foto").split('|'):
            self.taskstoreFotos.append([foto])

        flowbox = Gtk.FlowBox()
        button = Gtk.Button.new_from_icon_name("list-add", Gtk.IconSize.MENU)
        button.connect("clicked", self.do_click_add_foto)
        flowbox.add(button)

        gridFoto.attach(flowbox, 7, 3, 1, 1)

        flowbox = Gtk.FlowBox()
        button = Gtk.Button.new_from_icon_name("list-remove", Gtk.IconSize.MENU)
        button.connect("clicked", self.do_click_del_foto)
        flowbox.add(button)
        gridFoto.attach(flowbox, 7, 4, 1, 1)

        grid.attach(gridFoto, 4, 4, 3, 6)

        self.get_content_area().pack_start(grid, False, False, 0)
        self.show_all()

    def do_click_seleciona_ffmpeg(self, widget):  # @UnusedVariable
        debug("Selecionando o caminho do FFMPEG")

        dialog = Gtk.FileChooserDialog("Selecione o caminho do ffmpeg ", self, Gtk.FileChooserAction.OPEN,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        caminho = self.editCaminhoFfmpeg.get_text().strip()
        if os.path.isfile(caminho):
            dialog.set_current_folder(caminho)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.editCaminhoFfmpeg.set_text(dialog.get_filename())
            debug("Caminho do ffmpeg selecionado: " + dialog.get_filename())

        dialog.destroy()

    def do_click_del_video(self, widget):  # @UnusedVariable
        self.remove_item("video")

    def do_click_add_video(self, widget):  # @UnusedVariable
        self.add_item("video")

    def do_click_del_foto(self, widget):  # @UnusedVariable
        self.remove_item("foto")

    def do_click_add_foto(self, widget):  # @UnusedVariable
        self.add_item("foto")

    def add_item(self, titulo):
        info = InputDialog(mainWindow, 'Informe a extensão do arquivo de ' + titulo, '', None).show_and_get_info()
        if info is not None:
            store = self.taskstoreVideos if titulo == "video" else self.taskstoreFotos
            store.append([info])

    def remove_item(self, titulo):
        debug("Removendo item da lista de " + titulo)
        tree = self.treeviewFotos
        store = self.taskstoreFotos
        if titulo == "video":
            store = self.taskstoreVideos
            tree = self.treeviewVideos

        select = tree.get_selection()
        treeiter = select.get_selected()

        if treeiter[1] is None:
            return show_message("Não é possível excluir", "É necessário selecionar um dos ítens para continuar.")

        store.remove(treeiter)

    def show_and_get_info(self):
        while self.run() == Gtk.ResponseType.OK:
            set_app_settings("remover_apos_copia", str(self.checkRemoverCopia.get_active()))
            set_app_settings("sobrescrever_arquivos", str(self.checkSobrescrever.get_active()))
            set_app_settings("recodificar_videos", str(self.checkRecode.get_active()))
            set_app_settings("caminho_ffmpeg", self.editCaminhoFfmpeg.get_text().strip())
            set_app_settings("codec_video", str(self.comboCodecs.get_active()))
            set_app_settings("apenas_fotos_e_videos", str(self.checkFotosVideos.get_active()))
            set_app_settings("exibir_resolucao_arquivos", str(self.checkExibirResolucao.get_active()))                 

            videos = ""
            for row in self.taskstoreVideos:
                videos = videos + "|" + row[0]
            videos = videos[1:]
            set_app_settings("extensoes_video", videos)

            fotos = ""
            for row in self.taskstoreFotos:
                fotos = fotos + "|" + row[0]
            fotos = fotos[1:]
            set_app_settings("extensoes_foto", fotos)

        self.destroy()
        return None


class LogViewerDialog(Gtk.Dialog):
    """
    Dialogo para exibição do log
    """
        
    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Log da aplicação", parent, 0, (Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(1024, 600)
        self.set_border_width(10)

        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_hexpand(True)
        scrolledwindow.set_vexpand(True)

        self.grid = Gtk.Grid()
        self.grid.attach(scrolledwindow, 0, 1, 3, 1)

        self.textview = Gtk.TextView()
        scrolledwindow.add(self.textview)

        # Carrega o arquivo de log
        self.textview.get_buffer().set_text(open(ARQUIVO_LOG).read())

        self.get_content_area().pack_start(self.grid, True, True, 0)
        self.show_all()

    def show_and_get_info(self):
        self.run()
        self.destroy()
        return None


class MapeamentoDialog(Gtk.Dialog):
    """
    Dialogo para mapeamento dos diretórios de destino
    """

    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Mapeamento dos diretórios de destino", parent, 0, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(500, 400)
        self.set_border_width(10)

        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_hexpand(True)
        scrolledwindow.set_vexpand(True)

        self.grid = Gtk.Grid()
        self.grid.attach(scrolledwindow, 0, 1, 3, 1)

        self.textview = Gtk.TextView()
        scrolledwindow.add(self.textview)

        # Carrega o mapeamento atual
        global gDicMapeamentoDirDestino
        lines = ""
        for key in sorted(gDicMapeamentoDirDestino.iterkeys()):
            lines = lines + key + " => " + gDicMapeamentoDirDestino[key] + "\n"

        self.textview.get_buffer().set_text(lines)

        self.get_content_area().pack_start(self.grid, True, True, 0)
        self.show_all()

    def show_and_get_info(self):
        global gDicMapeamentoDirDestino
        while self.run() == Gtk.ResponseType.OK:
            buf = self.textview.get_buffer()
            resp = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
            for line in resp.splitlines():
                key = line[:line.find("=>")].strip()
                value = line[line.find("=>") + 2:].strip()
                gDicMapeamentoDirDestino[key] = value

            print(str(gDicMapeamentoDirDestino))
            self.destroy()
            return None

        self.destroy()
        return None


class MainWindow(Gtk.Window):
    """
    Janela principal da aplicação
    """
    
    colunas = ["Copiar", "Status", "Arquivo", "Destino", "Tipo", "Tamanho", "Detalhes"]
    popupMenuTree = Gtk.Menu()

    def __init__(self):
        Gtk.Window.__init__(self, title="Photo Sync - " + VERSAO_APPLICACAO)

        self.set_icon_name("application-x-executable")
        Gtk.Settings().set_property('gtk_button_images', True)

        # Clipboar para cópia do texto
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        self.set_resizable(True)
        self.set_border_width(10)
        self.set_default_size(640, 480)
        self.set_size_request(640, 480)

        # Container principal
        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(4)
        grid.set_row_spacing(6)

        # Campo Origem
        grid.attach(Gtk.Label(label="Diretório de Origem:", halign=Gtk.Align.START), 0, 0, 1, 1)
        self.editOrigem = Gtk.Entry()
        self.editOrigem.set_activates_default(True)
        self.editOrigem.set_text(get_app_settings("dir_origem"))

        grid.attach(self.editOrigem, 1, 0, 6, 1)

        button = Gtk.Button.new_from_icon_name("folder-open", Gtk.IconSize.BUTTON)
        button.connect("clicked", self.do_click_origem)
        flowbox = Gtk.FlowBox()
        flowbox.add(button)
        grid.attach(flowbox, 7, 0, 1, 1)
        self.labelStatusFrom = Gtk.Label(label="", halign=Gtk.Align.START)
        grid.attach(self.labelStatusFrom, 0, 1, 8, 1)

        # Campo Destino
        grid.attach(Gtk.Label(label="Diretório de Destino:", halign=Gtk.Align.START), 0, 2, 1, 1)
        self.editDestino = Gtk.Entry()
        self.editDestino.set_text(get_app_settings("dir_destino"))
        grid.attach(self.editDestino, 1, 2, 6, 1)
        button = Gtk.Button.new_from_icon_name("folder-open", Gtk.IconSize.BUTTON)
        button.connect("clicked", self.do_click_destino)
        flowbox = Gtk.FlowBox()
        flowbox.add(button)

        grid.attach(flowbox, 7, 2, 1, 1)
        self.labelStatusTo = Gtk.Label(label="", halign=Gtk.Align.START)
        grid.attach(self.labelStatusTo, 0, 3, 8, 1)

        # Barra de botões

        # Ler aquivos
        self.buttonLerArquivos = create_icon_and_label_button("Atualizar", "view-refresh")
        self.buttonLerArquivos.connect("clicked", self.do_click_check_files)
        grid.attach(self.buttonLerArquivos, 0, 4, 1, 1)

        # Sincronizar
        self.buttonSyncArquivos = create_icon_and_label_button("Sincronizar", "system-run")
        self.buttonSyncArquivos.set_sensitive(False)
        self.buttonSyncArquivos.connect("clicked", self.do_click_sync_files)
        grid.attach(self.buttonSyncArquivos, 1, 4, 1, 1)

        # Mapeamento
        self.buttonMapeamento = create_icon_and_label_button("Mapeamento", "document-properties")
        self.buttonMapeamento.set_sensitive(False)
        self.buttonMapeamento.connect("clicked", self.do_click_mapeamento_dir)
        grid.attach(self.buttonMapeamento, 2, 4, 1, 1)

        # Configurações
        self.buttonConfig = create_icon_and_label_button("Configurações", "applications-system")
        self.buttonConfig.connect("clicked", self.do_click_config)
        grid.attach(self.buttonConfig, 3, 4, 1, 1)

        # Logs
        button = create_icon_and_label_button("Logs", "system-search")
        button.connect("clicked", self.do_click_logs)
        grid.attach(button, 4, 4, 1, 1)

        # Sair
        button = create_icon_and_label_button("Fechar", "window-close")
        button.connect("clicked", self.do_click_close)
        grid.attach(button, 7, 4, 1, 1)

        # grid de arquivos

        # Cria o grid
        self.store = Gtk.ListStore(bool, str, str, str, str, str, str)

        self.filtro = self.store.filter_new()
        # self.filtro.set_visible_func(self.do_filter_grid)
        cellRenderer = Gtk.CellRendererText()

        # Adiciona as colunas ao TreeView
        self.treeview = Gtk.TreeView(model=self.store)
        self.treeview.connect("button_press_event", self.do_show_popup)

        # Colunas 0 e 1 não são texto
        col1 = Gtk.TreeViewColumn("Copiar", Gtk.CellRendererToggle(), active=0)
        col1.set_sort_column_id(0)
        self.treeview.append_column(col1)

        col2 = Gtk.TreeViewColumn("Status", Gtk.CellRendererPixbuf(), icon_name=1)
        col2.set_sort_column_id(1)
        self.treeview.append_column(col2)

        # Adiciona as demais colunas
        for i, column_title in enumerate(self.colunas):
            column = Gtk.TreeViewColumn(column_title, cellRenderer, text=i)
            if i > 1:  # Colunas 0 e 1 são do checkbox e icon e foram adicionadas anteriormente
                self.treeview.append_column(column)
            self.store.set_sort_func(i, compareTreeItem, None)
            column.set_sort_column_id(i)

        self.treeview.connect("row-activated", self.on_tree_double_clicked)

        # Adiciona o treeview a um scrollwindow
        scrollableTreelist = Gtk.ScrolledWindow()
        scrollableTreelist.set_vexpand(True)
        scrollableTreelist.add(self.treeview)
        grid.attach(scrollableTreelist, 0, 5, 8, 8)

        # Label de seleção dos arquivos
        self.labelStatusCopia = Gtk.Label(label="", halign=Gtk.Align.START)
        grid.attach(self.labelStatusCopia, 0, 13, 8, 1)

        self.add(grid)

        i0 = Gtk.MenuItem("Desmarcar todos os arquivos")
        i0.connect("activate", self.do_desmarcar_todos)
        self.popupMenuTree.append(i0)
        i1 = Gtk.MenuItem("Marcar todos os videos")
        i1.connect("activate", self.do_marca_todos_videos)
        self.popupMenuTree.append(i1)
        i2 = Gtk.MenuItem("Marcar todas as fotos")
        i2.connect("activate", self.do_marca_todas_fotos)
        self.popupMenuTree.append(i2)
        i3 = Gtk.MenuItem("Marcar videos não H265")
        i3.connect("activate", self.do_marcar_nao_h265)
        self.popupMenuTree.append(i3)
        i4 = Gtk.MenuItem("Apagar arquivos marcados")
        i4.connect("activate", self.do_apagar_selecionados)
        self.popupMenuTree.append(i4)

        self.popupMenuTree.show_all()

    def do_show_popup(self, tv, event):  # @UnusedVariable
        if event.button == 3:
            self.popupMenuTree.popup(None, None, None, None, 0, Gtk.get_current_event_time())

    def do_apagar_selecionados(self, widget):  # @UnusedVariable
        debug("MenuItem: Apagar arquivos marcados")
        arquivos = self.do_monta_lista_arquivos_copiar()
        if len(arquivos) > 0:
            dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.QUESTION, Gtk.ButtonsType.YES_NO, "Confirmação da exclusão")
            dialog.format_secondary_text("Você realmente deseja remover os " + str(len(arquivos)) + " arquivos marcados?")
            response = dialog.run()
            if response == Gtk.ResponseType.YES:
                for arquivo in arquivos:
                    debug("Removendo arquivo " + arquivo)
                    os.remove(arquivo)
                self.do_monta_lista_arquivos()
            dialog.destroy()

    def do_marcar_nao_h265(self, widget):  # @UnusedVariable
        debug("MenuItem: Marcar videos não H265")
        for row in self.store:
            if self.is_video(row[2]) and 'hevc' not in row[6]:
                row[0] = True

        self.do_atualiza_contador_selecao()

    def do_marca_todas_fotos(self, widget):  # @UnusedVariable
        debug("MenuItem: Marcar todas as fotos")
        for row in self.store:
            if self.is_foto(row[2]):
                row[0] = True

    def do_marca_todos_videos(self, widget):  # @UnusedVariable
        debug("MenuItem: Marcar todos os videos")
        for row in self.store:
            if self.is_video(row[2]):
                row[0] = True

        self.do_atualiza_contador_selecao()

    def do_desmarcar_todos(self, widget):  # @UnusedVariable
        debug("MenuItem: Desmarcar todos os arquivos")
        for row in self.store:
            row[0] = False

        self.do_atualiza_contador_selecao()

    def do_click_origem(self, widget):  # @UnusedVariable
        self.do_seleciona_dir("origem")

    def do_click_destino(self, widget):  # @UnusedVariable
        self.do_seleciona_dir("destino")

    def do_seleciona_dir(self, titulo):
        debug("Selecionando diretório de " + titulo)

        editor = self.editOrigem if titulo == "origem" else self.editDestino

        dialog = Gtk.FileChooserDialog("Selecione o diretório de " + titulo, self, Gtk.FileChooserAction.SELECT_FOLDER,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        currentDir = editor.get_text().strip()
        if os.path.isdir(currentDir):
            dialog.set_current_folder(currentDir)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            editor.set_text(dialog.get_filename())
            debug("Diretório de " + titulo + " selecionado: " + dialog.get_filename())
            set_app_settings("dir_" + titulo, dialog.get_filename())

        dialog.destroy()

    def get_tipo_arquivo(self, arquivo):
        tipo = "Desconhecido"
        if self.is_foto(arquivo):
            tipo = "Foto"
        elif self.is_video(arquivo):
            tipo = "Video"
        return tipo

    def get_file_is_sync(self, arquivo):
        global gListaArquivosDestino
        arquivos = gListaArquivosDestino.get(os.path.basename(arquivo), [])
        tamanhoOrigem = os.stat(arquivo).st_size
        found = False
        if len(arquivos) > 0:
            for  dests in arquivos:
                found = found or tamanhoOrigem == os.stat(dests).st_size
        return found

    def get_icone_arquivo(self, sync):
        mover = 'True' == get_app_settings("remover_apos_copia")
        resp = "forward" if mover else "go-down"

        if sync:
            sobrescreve = 'True' == get_app_settings("sobrescrever_arquivos")
            resp = "gtk-stop" if sobrescreve else "ok"

        return resp

    def do_monta_lista_arquivos(self):
        active = gLeituraOrigemFinalizada and gLeituraDestinoFinalizada

        if active:
            debug("Populando a grid de arquivos")

            global gListaArquivosOrigem
            global gDicInfoArquivosOrigem
            global gDicMapeamentoDirDestino

            # Verifica se deve sobrescrever os arqivos existentes
            sobrescrever = 'True' == get_app_settings("sobrescrever_arquivos")

            self.store.clear()
            posSrc = len(self.editOrigem.get_text()) + 1
            for arquivo in gListaArquivosOrigem:
                sync = self.get_file_is_sync(arquivo)
                icon = self.get_icone_arquivo(sync)
                tamanho = to_human_size(os.stat(arquivo).st_size)
                detalhes = gDicInfoArquivosOrigem[arquivo]
                arquivoAbr = arquivo[posSrc:]
                tipoArquivo = self.get_tipo_arquivo(arquivo)
                destino = get_destino_arquivo(arquivo)

                # Se for para sobrescrever, sync deve ser sempre falso
                if sobrescrever:
                    sync = False

                self.store.append([
                    not sync,
                    icon,
                    arquivoAbr,
                    destino,
                    tipoArquivo,
                    tamanho,
                    detalhes
                ])

            # Habilita os botões
            self.buttonLerArquivos.set_sensitive(active)
            self.buttonSyncArquivos.set_sensitive(active)
            self.buttonMapeamento.set_sensitive(active)

            # Atualiza o contador
            self.do_atualiza_contador_selecao()
            debug("Grid de arquivos populada")

    def do_read_file_list_origem(self):
        global gListaArquivosOrigem
        global gLeituraOrigemFinalizada
        global gDicInfoArquivosOrigem
        gDicInfoArquivosOrigem = {}

        # Monta a lista de arquivos
        gListaArquivosOrigem = [y for x in os.walk(self.editOrigem.get_text()) for y in glob(os.path.join(x[0], '*.*'))]
        tamanho = 0
        for arquivo in gListaArquivosOrigem:
            try:
                # Carrega a informação do arquivo
                gDicInfoArquivosOrigem[arquivo] = self.get_file_info(arquivo)

                tamanho = tamanho + os.stat(arquivo).st_size  # in bytes
            except:
                debug("Falha ao ler o arquivo de origem " + arquivo)

        self.labelStatusFrom.set_text("Arquivos no diretório de origem: " + str(len(gListaArquivosOrigem)) + " (" + to_human_size(tamanho) + ")")
        debug(self.labelStatusFrom.get_text())
        gLeituraOrigemFinalizada = True
        self.do_monta_lista_arquivos()
        debug("Consulta da lista de arquivos de origem concluída")

    def do_read_file_list_destino(self):
        global gLeituraDestinoFinalizada
        global gListaArquivosDestino
        gListaArquivosDestino = {}
        lista_arquivos_destino = [y for x in os.walk(self.editDestino.get_text()) for y in glob(os.path.join(x[0], '*.*'))]
        tamanho = 0
        for arquivo in lista_arquivos_destino:
            try:
                tamanho = tamanho + os.stat(arquivo).st_size  # in bytes
                nome = os.path.basename(arquivo)
                arquivos = gListaArquivosDestino.get(nome, [])
                arquivos.append(arquivo)
                gListaArquivosDestino[nome] = arquivos
            except:
                debug("Falha ao ler o arquivo de destino " + arquivo)

        self.labelStatusTo.set_text("Arquivos no diretório de destino: " + str(len(lista_arquivos_destino)) + " (" + to_human_size(tamanho) + ")")
        debug(self.labelStatusTo.get_text())
        gLeituraDestinoFinalizada = True
        self.do_monta_lista_arquivos()
        debug("Consulta da lista de arquivos de destino concluída")

    def do_click_check_files(self, widget):  # @UnusedVariable
        debug("Validando os diretórios")

        if not os.path.isdir(self.editOrigem.get_text()):
            return show_message("Diretório inexistente", "Não foi possível encontrar o diretório de origem.")

        if not os.path.isdir(self.editDestino.get_text()):
            return show_message("Diretório inexistente", "Não foi possível encontrar o diretório de destino.")

        debug("Verificando a lista de arquivos")

        global gListaArquivosOrigem
        global gListaArquivosDestino
        global gLeituraOrigemFinalizada
        global gLeituraDestinoFinalizada

        gListaArquivosOrigem = []
        gListaArquivosDestino = {}
        gLeituraOrigemFinalizada = False
        gLeituraDestinoFinalizada = False

        # Desabilita os botões
        self.buttonLerArquivos.set_sensitive(False)
        self.buttonSyncArquivos.set_sensitive(False)
        self.buttonMapeamento.set_sensitive(False)

        self.store.clear()

#         Thread(target=self.do_read_file_list_origem).start()
#         Thread(target=self.do_read_file_list_destino).start()

        # Compara a lista de arquivos da origem com o destino
        self.do_read_file_list_origem()
        self.do_read_file_list_destino()

    def do_atualiza_contador_selecao(self):
        cont = 0
        cont_video = 0
        cont_foto = 0
        cont_outro = 0
        size = 0
        size_video = 0
        size_foto = 0
        size_outro = 0

        for row in self.store:
            if row[0]:
                arquivo = self.editOrigem.get_text() + os.sep + row[2]
                cont += 1
                size += os.stat(arquivo).st_size

                if self.is_video(arquivo):
                    cont_video += 1
                    size_video += os.stat(arquivo).st_size
                elif self.is_foto(arquivo):
                    cont_foto += 1
                    size_foto += os.stat(arquivo).st_size
                else:
                    cont_outro += 1
                    size_outro += os.stat(arquivo).st_size

        self.labelStatusCopia.set_text("Arquivos selecionados: " + str(cont) + " / " + str(len(self.store)) + " (" + to_human_size(size) + ") - Videos: " + 
                                         str(cont_video) + " (" + to_human_size(size_video) + ") - Fotos: " + str(cont_foto) + " (" + to_human_size(size_foto) + ") - Outros: " + str(cont_outro) + "(" + to_human_size(size_outro) + ")")

    def do_monta_lista_arquivos_copiar(self):
        resp = []
        for row in self.store:
            if row[0]:
                resp.append(self.editOrigem.get_text() + os.sep + row[2])
        return resp

    def is_video(self, arquivo):
        for ext in get_app_settings("extensoes_video").split('|'):
            if arquivo.lower().endswith(ext.lower()):
                return True
        return False

    def is_foto(self, arquivo):
        for ext in get_app_settings("extensoes_foto").split('|'):
            if arquivo.lower().endswith(ext.lower()):
                return True
        return False

    def do_obter_lista_fotos(self, videos):
        resp = []
        for arquivo in videos:
            if self.is_foto(arquivo):
                resp.append(arquivo)
        return resp

    def do_obter_lista_videos(self, arquivos):
        resp = []
        for arquivo in arquivos:
            if self.is_video(arquivo):
                resp.append(arquivo)
        return resp

    def do_click_mapeamento_dir(self, widget):  # @UnusedVariable
        debug("Mapeamento de diretórios")

        MapeamentoDialog(mainWindow).show_and_get_info()
        self.do_monta_lista_arquivos()

    def do_click_sync_files(self, widget):  # @UnusedVariable
        debug("Montando a lista dos arquivos que serão copiados")

        # Recupera a lista de arquivos selecionados
        arquivos = self.do_monta_lista_arquivos_copiar()

        # Filtra apenas videos e fotos
        if 'True' == get_app_settings("apenas_fotos_e_videos"):
            debug("Filtrando apenas videos e fotos")
            medias = self.do_obter_lista_fotos(arquivos)
            medias.extend(self.do_obter_lista_videos(arquivos))
            arquivos = medias

        debug("Iniciando a cópia dos arquivos")
        # Efetua a cópia dos arquivos
        dialogArquivos = FileCopyProgressDialog(mainWindow, arquivos, self.editDestino.get_text())
        dialogArquivos.run()
        dialogArquivos.mustStop = True
        if dialogArquivos.failed:
            show_message("Falha na cópia dos arquivos!", "Ocorreram falhas durante a cópia de pelo menos um arquivo, verifique o log para mais informações.")

        dialogArquivos.destroy()
        debug("Cópia dos arquivos finalizada")

        # Verifica se deve recomprimir os videos
        if 'True' == get_app_settings("recodificar_videos"):
            debug("Montando a lista de videos a serem compactados")
            arquivos = self.do_obter_lista_videos(arquivos)
            if len(arquivos) > 0:
                debug("Compactando " + str(len(arquivos)) + " video(s).")

                # Salva o STDOUT para o caso do ffmpeg ser interrompido
                savedStdout = sys.stdout

                # Efetua a cópia dos arquivos
                dialogVideo = VideoEncodeProgressDialog(mainWindow, arquivos, self.editDestino.get_text(),)
                dialogVideo.run()
                # Força a interrupção da conversão caso o usuário pressione cancel
                dialogVideo.mustStop = True
                if dialogVideo.failed:
                    show_message("Falha na conversão!", "Ocorreram falhas durante a conversão de pelo menos uma video, verifique o log para mais informações.")

                global gProcessoFfmpeg
                if gProcessoFfmpeg is not None:
                    try:
                        gProcessoFfmpeg.kill()
                        debug("O processo do ffmpeg foi interrompido pelo usuário.")
                    except OSError:
                        debug("O processo do ffmpeg foi finalizado com sucesso.")

                dialogVideo.destroy()
                debug("Codificação dos vídeos finalizada")

                # Retorna o STDOUT original
                sys.stdout = savedStdout

        show_message("Concluído!", "Operação de cópia dos arquivos finalizada!")

    def do_click_config(self, widget):  # @UnusedVariable
        debug("Configurando a aplicação")
        ConfigDialog(mainWindow).show_and_get_info()

    def do_click_logs(self, widget):  # @UnusedVariable
        debug("Visualizando os logs")
        LogViewerDialog(mainWindow).show_and_get_info()

    def do_click_close(self, widget):  # @UnusedVariable
        on_close(None, None)

    def on_tree_double_clicked(self, widget, row, col):  # @UnusedVariable
        debug("Duplo click na lista de arquivos (" + str(row) + "," + str(col.get_sort_column_id()) + ")")
        select = self.treeview.get_selection()
        model, treeiter = select.get_selected()
        self.store.set_value(treeiter, 0, not model[treeiter][0])
        self.do_atualiza_contador_selecao()

    def get_file_info(self, arquivo):
    
        captureInfo = 'True' == get_app_settings("exibir_resolucao_arquivos")
    
        if not captureInfo or not self.is_foto(arquivo) and not self.is_video(arquivo):
            return ""

        pattern = re.compile("(Duration: [0-9]{2,}:[0-9]{2,}:[0-9]{2,})|(Video: [^\s]+)|([0-9]{2,}x[0-9]{2,})|([0-9|.]+ fps)|(Audio: [^\s]+)|([0-9]+ Hz)")
        args = [get_caminho_ffmpeg(), "-hide_banner", "-i", arquivo]

        global gProcessoFfmpeg
        gProcessoFfmpeg = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

        lines = ""
        # Inicia o processo e concatena as linhas do output
        for line in iter(gProcessoFfmpeg.stdout.readline, ''):

            # Considera apenas as linhas essenciais
            if line.find("Stream #0") or line.find(" Duration:"):
                lines = lines + line

        if "Duration: 00:00:00" in lines:
            lines = lines.replace("Duration: 00:00:00", "")
            lines = lines.replace("Video: ", "")

        # Recupera o texto dos grupos da regex
        resp = ""
        for m in pattern.finditer(lines):
            resp = resp + m.group() + " "

        # Finaliza o processo do ffmpeg
        gProcessoFfmpeg.stdout.close()
        gProcessoFfmpeg.wait()

        return resp


def get_destino_arquivo(arquivo):
    global gDicMapeamentoDirDestino
    if gDicMapeamentoDirDestino is None:
        gDicMapeamentoDirDestino = {}

    nome = os.path.basename(arquivo)
    data = datetime.datetime.fromtimestamp(os.path.getmtime(arquivo))

    # Destino: /YYYY/yyyy-MM-dd/arquivo
    destino = str(data.year) + os.sep + str(data.year) + "-" + str(data.month).zfill(2) + "-" + str(data.day).zfill(2)

    if destino not in gDicMapeamentoDirDestino:
        gDicMapeamentoDirDestino[destino] = destino

    return gDicMapeamentoDirDestino[destino] + os.sep + nome


def create_icon_and_label_button(label, icon):
    """
    Cria um botão com um ícone e um texto
    """
    
    debug("Criando botão: " + label)
    button = Gtk.Button.new()
    bGrid = Gtk.Grid()
    bGrid.set_column_spacing(6)
    bGrid.attach(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR), 0, 0, 1, 1)
    bGrid.attach(Gtk.Label(label=label, halign=Gtk.Align.CENTER), 1, 0, 1, 1)
    bGrid.show_all()
    button.add(bGrid)
    return button


def compareTreeItem(model, row1, row2, user_data):  # @UnusedVariable
    """
    Compara 2 ítens de uma tree
    """
    
    sort_column, _ = model.get_sort_column_id()
    value1 = model.get_value(row1, sort_column)
    value2 = model.get_value(row2, sort_column)

    if value1 < value2:
        return -1
    elif value1 == value2:
        return 0
    else:
        return 1


def show_message(titulo, msg):
    """
    Exibe um Dialog de aviso
    """

    debug("Exibindo dialog: " + titulo + " - " + msg)
    global mainWindow
    dialog = Gtk.MessageDialog(mainWindow, 0, Gtk.MessageType.INFO, Gtk.ButtonsType.CLOSE, titulo)
    dialog.format_secondary_text(msg)
    dialog.run()
    dialog.destroy()
    return None


def indent_xml(elem, level=0):
    """
    Formata um arquivo XML
    """
    
    i = "\n" + level * "\t"
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "\t"
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent_xml(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def set_app_settings(xmlTag, value):
    """
    Salva uma configuração da aplicação
    """

    debug("Salvando configuração da aplicação: " + xmlTag + " = " + value)
    if not os.path.isfile(ARQUIVO_XML_SETTINGS):
        indent_and_save_xml(ET.Element('config'), ARQUIVO_XML_SETTINGS)

    configTree = ET.parse(ARQUIVO_XML_SETTINGS, ET.XMLParser(remove_comments=False, strip_cdata=False))
    root = configTree.getroot()

    # Remove o nó se já existir
    if configTree.find("./" + xmlTag) is not None:
        root.remove(configTree.find("./" + xmlTag))

    # Se o valor não for nulo, adicionar o novo nó
    if value is not None and value.strip():
        ET.SubElement(root, xmlTag).text = value

    indent_and_save_xml(configTree.getroot(), ARQUIVO_XML_SETTINGS)


def get_app_settings(xmlTag):
    """
    Recupera uma configuração da aplicação
    """
    
    nodeCaminho = ET.parse(ARQUIVO_XML_SETTINGS, ET.XMLParser(remove_comments=False, strip_cdata=False)).find("./" + xmlTag)
    return None if nodeCaminho is None else nodeCaminho.text


def indent_and_save_xml(rootNode, arquivoXml):
    """
    Formata e salva um arquivo XML
    """

    debug("Salvando o arquivo XML: " + arquivoXml)
    indent_xml(rootNode)
    prettyXml = ET.tostring(rootNode, encoding="UTF-8", method="xml", xml_declaration=True)
    arquivo = open(arquivoXml, "wb")
    arquivo.write(prettyXml)
    arquivo.close()


def debug(msg=''):
    """
    Loga uma mensagem
    """
    gLogger.debug(str(msg).strip())


def to_human_size(nbytes):
    """
    Converte uma quantidade de bytes em formato de fácil visualização
    """
    
    human = nbytes
    rank = 0
    if nbytes != 0:
        rank = int((math.log10(nbytes)) / 3)
        rank = min(rank, len(UNIDADES) - 1)
        human = nbytes / (1024.0 ** rank)
    f = ('%.2f' % human).rstrip('0').rstrip('.')
    return '%s %s' % (f, UNIDADES[rank])


def on_close(self, widget):  # @UnusedVariable
    """
    Fecha a aplicação, liberando o FileHandler do log
    """
    
    logHandler.close()
    gLogger.removeHandler(logHandler)
    sys.exit()


def get_codec_info(codec):
    """
    Recupera os parâmtros do ffmpeg para conversão
    """

    resp = None
    if VIDEO_H265 == codec:
        resp = {"params":["-c:v", "libx265", "-acodec", "aac", "-strict", "-2"], "sufixo":"_H265.mp4"}
    elif VIDEO_H264 == codec:
        resp = {"params":["-c:v", "libx264", "-acodec", "aac", "-strict", "-2"], "sufixo":"_H264.mp4"}
    elif VIDEO_VP8 == codec:
        resp = {"params":["-c:v", "libvpx", "-b:v", "1M", "-c:a", "libvorbis"], "sufixo":"_VP8.webm"}
    elif VIDEO_VP9 == codec:
        resp = {"params":["-c:v", "libvpx-vp9", "-b:v", "2M", "-c:a", "libopus"], "sufixo":"_VP9.webm"}
    return resp


def get_caminho_ffmpeg():
    """
    Recupera o caminho onde o ffmpeg está instalado
    """
    
    app = get_app_settings("caminho_ffmpeg")
    return app if app is not None else "ffmpeg"


def get_ffmpeg_features():
    
    """
    Recupera uma lista com as features do ffmpeg: Ex: --enable-libx264
    """
    global gListaFfmpegFeatures

    if gListaFfmpegFeatures is None:
        gProcessoFfmpeg = subprocess.Popen([get_caminho_ffmpeg()], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

        linhas = ""
        for line in iter(gProcessoFfmpeg.stdout.readline, ''):
            if "--" in line:
                linhas = linhas + line

        gProcessoFfmpeg.stdout.close()
        gProcessoFfmpeg.wait()

        gListaFfmpegFeatures = []
        pattern = re.compile("--enable-[^\s]+|disable-[^\s]+")
        for m in pattern.finditer(linhas):
            gListaFfmpegFeatures.append(m.group())

    return gListaFfmpegFeatures

# Constantes da aplicação


VERSAO_APPLICACAO = "v1.0"  #  Versão da aplicação


UNIDADES = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']  # Unidades de conversão bytes -> Si
DIR_APPLICATION = os.path.dirname(os.path.realpath(__file__))  # Diretório da aplicação
ARQUIVO_XML_SETTINGS = DIR_APPLICATION + os.sep + "settings.xml"  # Arquivo de configuração da aplicação
ARQUIVO_LOG = DIR_APPLICATION + os.sep + "application.log"  # Arquivo de log

# Codecs de Video
VIDEO_H265 = "Video H265"
VIDEO_H264 = "Video H264"
VIDEO_VP8 = "Video VP8"
VIDEO_VP9 = "Video VP9"
CODECS_VIDEO = []

# Variáveis globais da aplicação
# Nota: por convenção, as variáveis globais são camelCase e iniciam com um 'g' 

gDebugMode = False  # True para exibir mensagens de debug

# Controle do ffmpeg
gProcessoFfmpeg = None  # Representa a instância do processo do ffmpeg
gListaFfmpegFeatures = None  # Dicionário com as features de compilação do ffmpeg

# Variáveis dos arquivos de origem
gLeituraOrigemFinalizada = False  # Sinaliza o fim da thread de leitura de arquivos de origem 
gListaArquivosOrigem = None  # Lista de arquivos no diretório de origem
gDicInfoArquivosOrigem = None  # Dicionário com informações sobre os arquivos

# Variáveis dos arquivos de destino
gLeituraDestinoFinalizada = False  # Sinaliza o fim da thread de leitura de arquivos de destino
gListaArquivosDestino = None  # Lista de arquivos no diretório de destino
gDicMapeamentoDirDestino = {}  # Mapeamento dos diretórios de destino

# Remove o arquivo de log anterior e cria o gLogger
if os.path.isfile(ARQUIVO_LOG):
    os.remove(ARQUIVO_LOG)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(message)s')
logHandler = logging.FileHandler(ARQUIVO_LOG)

gLogger = logging.getLogger('-')  # Logger da aplicação
gLogger.addHandler(logHandler)

# Lê os parâmetros da aplicação
try:
    opts, args = getopt.getopt(sys.argv[1:], "h", [])
except getopt.GetoptError:
    print('photosync.py -h (help)')
    sys.exit(2)
for opt, arg in opts:
    if opt == '-h':
        print("\nPrograma para sincronização de arquivos")
        print("\nUso: photosync.py -h (help)")
        print("\nExemplo: ./photosync.py")
        sys.exit()

# Força UTF-8 por padrão
if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding("utf-8")

if not os.path.isfile(ARQUIVO_XML_SETTINGS):
    set_app_settings("dirDestino", str(os.path.expanduser('~')))
    set_app_settings("dir_origem", str(os.path.expanduser('~')))
    set_app_settings("extensoes_video", "wmv|avi|mpg|3gp|mov|m4v|mts|mp4")
    set_app_settings("extensoes_foto", "dof|arw|raw|jpg|jpeg|png|nef")
    set_app_settings("codec_video", "0")
    set_app_settings("caminho_ffmpeg", "ffmpeg")

mainWindow = MainWindow()

# Verifica a presença do ffmpeg
if not spawn.find_executable(get_caminho_ffmpeg()):
    info = InputDialog(mainWindow, 'Informe o caminho para o ffmpeg', '', None).show_and_get_info()
    if info is None or not spawn.find_executable(info):
        print("Não foi possível encontrar o aplicativo necessário ffmpeg.")
        print("Verifique a configuração do caminho do ffmpeg no arquivo settings.xml")
        print("A configuração atual é: " + get_caminho_ffmpeg())
        sys.exit(2)
    else:
        set_app_settings("caminho_ffmpeg", info)

# Exibe as aopções de codec de acordo com a disponibilidade do ffmpeg
if "--enable-libx264" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_H264)

if "--enable-libx265" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_H265)

if "--enable-libvpx" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_VP8)
    CODECS_VIDEO.append(VIDEO_VP9)

# Calling GObject.threads_init() is not needed for PyGObject 3.10.2+
GObject.threads_init()

# Monta a UI
mainWindow.connect('delete-event', on_close)
mainWindow.show_all()
Gtk.main()
